from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Nanogrid Central Hub")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class HouseData(BaseModel):
    id: str
    P_G: float      # generation, W
    P_D: float      # demand, W
    P_avail: float  # battery power available for discharge, W
    C: float        # cost per W for this house's battery


class NanogridSystem(BaseModel):
    houses: List[HouseData]


class HouseResult(BaseModel):
    id: str
    P_surplus: float
    P_alloc: float
    P_local_deficit: float


# ---- Core Algorithm 2 logic, reusable by both manual and hardware endpoints ----
def run_allocation(houses: List[HouseData]) -> List[HouseResult]:
    # Step 1: per-house surplus (Algorithm 2, lines 3-5)
    surplus = {}
    for h in houses:
        delta = h.P_G - h.P_D
        surplus[h.id] = max(0.0, delta)

    # Step 2: global totals (lines 6-7)
    P_G_total = sum(h.P_G for h in houses)
    P_D_total = sum(h.P_D for h in houses)
    delta_total = P_G_total - P_D_total

    results = []

    if delta_total >= 0:
        # Line 8-10: network sharing covers everything
        for h in houses:
            results.append(HouseResult(
                id=h.id,
                P_surplus=surplus[h.id],
                P_alloc=0.0,
                P_local_deficit=0.0
            ))
        return results

    # Line 11-12: there's a global deficit
    P_req = -delta_total
    P_available = sum(h.P_avail for h in houses)

    if P_available >= P_req:
        # Line 13-16: battery sufficient -> minimize cost, greedy by cheapest C first
        alloc = {h.id: 0.0 for h in houses}
        remaining = P_req
        for h in sorted(houses, key=lambda x: x.C):
            if remaining <= 0:
                break
            take = min(h.P_avail, remaining)
            alloc[h.id] = take
            remaining -= take

        for h in houses:
            results.append(HouseResult(
                id=h.id,
                P_surplus=surplus[h.id],
                P_alloc=alloc[h.id],
                P_local_deficit=0.0
            ))
        return results

    # Line 17-22: battery insufficient -> proportional demand-share allocation
    for h in houses:
        share = h.P_D / P_D_total if P_D_total > 0 else 0.0
        p_alloc = share * P_available
        results.append(HouseResult(
            id=h.id,
            P_surplus=surplus[h.id],
            P_alloc=p_alloc,
            P_local_deficit=h.P_D - p_alloc
        ))
    return results


@app.get("/")
def home():
    return {"message": "Nanogrid Central Hub is running"}


# ---- Manual/testing endpoint (used by the frontend form) ----
@app.post("/nanogrids/allocate", response_model=List[HouseResult])
def allocate(system: NanogridSystem):
    return run_allocation(system.houses)


# ---- Hardware endpoints: each House Arduino pushes its own data, then polls its own result ----
house_data_store: Dict[str, HouseData] = {}
house_results_store: Dict[str, HouseResult] = {}

EXPECTED_HOUSE_IDS = {"H1", "H2", "H3", "H4"}


@app.post("/houses/{house_id}/data")
def submit_house_data(house_id: str, data: HouseData):
    house_data_store[house_id] = data

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
        return {"id": house_id, "P_surplus": 0.0, "P_alloc": 0.0, "P_local_deficit": 0.0}
    return house_results_store[house_id]


@app.get("/houses")
def get_all_house_data():
    return {
        "reported": list(house_data_store.keys()),
        "data": house_data_store,
        "results": house_results_store,
    }