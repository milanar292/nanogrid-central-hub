from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Optional
from fastapi.middleware.cors import CORSMiddleware
import time

app = FastAPI(title="Nanogrid Central Hub")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Battery model (same for every house; change here) ----
SOC_MIN = 20.0           # % - never discharge below this
SOC_MAX = 80.0           # % - never charge above this
HORIZON_H = 1.0          # hours - usable energy is spread over this time to get a power in W
P_BATT_RATING = 20.0     # W   - max charge / discharge power of one battery (same as PMAX_W and PCHG_MAX_W in the Arduino sketch)
DEFAULT_CAPACITY_WH = 30.0  # dummy battery capacity per house
STALE_AFTER_S = 15.0     # house data older than this is shown as stale


class HouseData(BaseModel):
    id: str
    P_G: float      # generation, W
    P_D: float      # demand used by the algorithm, W (a switched-OFF load still counts as its rated power)
    P_load: Optional[float] = None   # ACTUAL measured consumption, W (0 W when loads are OFF) - for display
    P_avail: float = 0.0   # battery power available for discharge, W (only used if soc_pct is NOT sent)
    C: float        # cost per W for this house's battery
    soc_pct: Optional[float] = None       # battery state of charge, % (from the SOC potentiometer)
    capacity_Wh: float = DEFAULT_CAPACITY_WH
    source: str = "live"                  # "live" (hardware) or "dummy"
    rtc: Optional[str] = None             # time string from the DS3231, optional
    loads: Optional[Dict[str, float]] = None  # per-load watts, e.g. {"L1": 9.1, "L2": 0}


class NanogridSystem(BaseModel):
    houses: List[HouseData]


class HouseResult(BaseModel):
    id: str
    P_surplus: float
    P_alloc: float
    P_recv: float = 0.0    # power RECEIVED by this house, W
    P_local_deficit: float
    P_supply: float = 0.0   # battery power drawn FROM this house, W
    P_stored: float = 0.0   # surplus energy stored in this house's battery, W
    # ---- battery view ----
    soc_pct: Optional[float] = None
    P_discharge_max: float = 0.0   # how much this battery CAN discharge now, W
    P_charge_max: Optional[float] = None  # how much this battery CAN charge now, W (None = no limit known)
    P_curtailed: float = 0.0       # surplus that could not be stored (battery full / rating limit), W
    battery_state: str = "idle"    # "charging" | "discharging" | "idle"


def fill_p_load(h: HouseData) -> HouseData:
    """Make sure P_load is always set: measured total of the loads, else fall back to P_D."""
    if h.P_load is None:
        h.P_load = sum(h.loads.values()) if h.loads else h.P_D
    return h


def battery_limits(h: HouseData):
    """Return (max_discharge_W, max_charge_W). max_charge is None when SOC is unknown."""
    if h.soc_pct is None:
        return max(0.0, h.P_avail), None
    soc = min(100.0, max(0.0, h.soc_pct))
    discharge = max(0.0, soc - SOC_MIN) / 100.0 * h.capacity_Wh / HORIZON_H
    charge = max(0.0, SOC_MAX - soc) / 100.0 * h.capacity_Wh / HORIZON_H
    return min(discharge, P_BATT_RATING), min(charge, P_BATT_RATING)


def _state(stored: float, drawn: float) -> str:
    if stored > 0.001:
        return "charging"
    if drawn > 0.001:
        return "discharging"
    return "idle"


# ---- Core Algorithm 2 logic, reusable by both manual and hardware endpoints ----
# NOTE: this uses P_D (algorithm demand), NOT P_load. Do not change that.
def run_allocation(houses: List[HouseData]) -> List[HouseResult]:
    limits = {h.id: battery_limits(h) for h in houses}
    avail = {hid: lim[0] for hid, lim in limits.items()}
    chg_max = {hid: lim[1] for hid, lim in limits.items()}

    # Step 1: per-house surplus (Algorithm 2, lines 3-5)
    surplus = {}
    for h in houses:
        delta = h.P_G - h.P_D
        surplus[h.id] = max(0.0, delta)

    # Step 2: global totals (lines 6-7)
    P_G_total = sum(h.P_G for h in houses)
    P_D_total = sum(h.P_D for h in houses)
    delta_total = P_G_total - P_D_total
    total_surplus = sum(surplus.values())
    total_deficit = sum(max(0.0, h.P_D - h.P_G) for h in houses)

    results = []

    def make(h, **kw):
        return HouseResult(
            id=h.id,
            P_surplus=surplus[h.id],
            soc_pct=h.soc_pct,
            P_discharge_max=avail[h.id],
            P_charge_max=chg_max[h.id],
            battery_state=_state(kw.get("P_stored", 0.0), kw.get("P_supply", 0.0)),
            **kw,
        )

    if delta_total >= 0:
        # Network sharing covers everything, no battery discharge needed.
        # Excess energy beyond all deficits is stored proportionally to surplus,
        # but never more than the battery can still accept (SOC_MAX / rating).
        excess = total_surplus - total_deficit
        for h in houses:
            share = (surplus[h.id] / total_surplus) * excess if total_surplus > 0 else 0.0
            cap = chg_max[h.id]
            stored = share if cap is None else min(share, cap)
            results.append(make(
                h,
                P_alloc=0.0,
                P_recv=max(0.0, h.P_D - h.P_G),
                P_local_deficit=0.0,
                P_supply=0.0,
                P_stored=stored,
                P_curtailed=share - stored,
            ))
        return results

    # total_surplus < total_deficit: global deficit
    P_req = total_deficit - total_surplus
    P_available = sum(avail.values())

    if P_available >= P_req:
        # Battery sufficient -> minimize cost, greedy by cheapest C first
        alloc = {h.id: 0.0 for h in houses}
        remaining = P_req
        for h in sorted(houses, key=lambda x: x.C):
            if remaining <= 0:
                break
            take = min(avail[h.id], remaining)
            alloc[h.id] = take
            remaining -= take
    else:
        # Battery insufficient -> every battery fully drawn
        alloc = dict(avail)

    total_drawn = sum(alloc.values())
    supply = total_surplus + total_drawn

    for h in houses:
        deficit_i = max(0.0, h.P_D - h.P_G)
        if deficit_i > 0:
            p_recv = (deficit_i / total_deficit) * supply
        else:
            p_recv = 0.0
        results.append(make(
            h,
            P_alloc=alloc[h.id],
            P_recv=p_recv,
            P_local_deficit=deficit_i - p_recv,
            P_supply=alloc[h.id],
            P_stored=0.0,
        ))
    return results


@app.get("/")
def home():
    return {"message": "Nanogrid Central Hub is running"}


# ---- Manual/testing endpoint (used by the frontend form) ----
@app.post("/nanogrids/allocate", response_model=List[HouseResult])
def allocate(system: NanogridSystem):
    for h in system.houses:
        fill_p_load(h)
    return run_allocation(system.houses)


@app.get("/config")
def get_config():
    return {
        "soc_min": SOC_MIN, "soc_max": SOC_MAX, "horizon_h": HORIZON_H,
        "p_batt_rating": P_BATT_RATING, "stale_after_s": STALE_AFTER_S,
    }


# ---- Hardware endpoints: each House Arduino pushes its own data, then polls its own result ----
house_data_store: Dict[str, HouseData] = {}
house_results_store: Dict[str, HouseResult] = {}
house_seen_at: Dict[str, float] = {}

EXPECTED_HOUSE_IDS = {"H1", "H2", "H3", "H4"}


@app.post("/houses/{house_id}/data")
def submit_house_data(house_id: str, data: HouseData):
    fill_p_load(data)
    house_data_store[house_id] = data
    house_seen_at[house_id] = time.time()

    # Once all 4 houses have reported in, recompute allocation for everyone
    if EXPECTED_HOUSE_IDS.issubset(house_data_store.keys()):
        houses = list(house_data_store.values())
        results = run_allocation(houses)
        for r in results:
            house_results_store[r.id] = r

    return {"message": f"Data received from {house_id}", "houses_reported": list(house_data_store.keys())}


@app.get("/houses/{house_id}/result", response_model=HouseResult)
def get_house_result(house_id: str):
    if house_id not in house_results_store:
        return {"id": house_id, "P_surplus": 0.0, "P_alloc": 0.0, "P_recv": 0.0, "P_local_deficit": 0.0, "P_supply": 0.0, "P_stored": 0.0}
    return house_results_store[house_id]


@app.get("/houses")
def get_all_house_data():
    now = time.time()
    return {
        "reported": list(house_data_store.keys()),
        "data": house_data_store,
        "results": house_results_store,
        "age_s": {hid: round(now - t, 1) for hid, t in house_seen_at.items()},
        "stale_after_s": STALE_AFTER_S,
    }