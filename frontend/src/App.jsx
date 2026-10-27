import { useState, useEffect, useRef } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts'
import './App.css'

const initialHouses = [
  { id: 'H1', P_G: 100, P_D: 120, soc_pct: 50, capacity_Wh: 100, C: 0.5 },
  { id: 'H2', P_G: 90, P_D: 100, soc_pct: 20, capacity_Wh: 100, C: 0.3 },
  { id: 'H3', P_G: 80, P_D: 90, soc_pct: 40, capacity_Wh: 100, C: 0.4 },
  { id: 'H4', P_G: 70, P_D: 75, soc_pct: 20, capacity_Wh: 100, C: 0.6 },
]

const fmt = (v) => (v === null || v === undefined ? '-' : `${Number(v).toFixed(1)} W`)

function BatteryBlock({ result }) {
  if (!result || result.soc_pct === null || result.soc_pct === undefined) return null
  const soc = Math.max(0, Math.min(100, result.soc_pct))
  return (
    <div className="battery-block">
      <div className="battery-head">
        <span className="result-label">Battery SOC</span>
        <span className="result-val">{soc.toFixed(0)}%</span>
        <span className={`battery-state ${result.battery_state}`}>{result.battery_state}</span>
      </div>
      <div className="soc-bar">
        <div className="soc-fill" style={{ width: `${soc}%` }} />
        <div className="soc-mark" style={{ left: '20%' }} title="20% min" />
        <div className="soc-mark" style={{ left: '80%' }} title="80% max" />
      </div>
      <div className="battery-rows">
        <div><span className="result-label">Can discharge</span><span className="result-val">{fmt(result.P_discharge_max)}</span></div>
        <div><span className="result-label">Can charge</span><span className="result-val">{fmt(result.P_charge_max)}</span></div>
        <div><span className="result-label">Wasted (cannot store)</span><span className="result-val">{fmt(result.P_curtailed)}</span></div>
      </div>
    </div>
  )
}

const HOUSE_IDS = ['H1', 'H2', 'H3', 'H4']

function App() {
  const [mode, setMode] = useState('manual') // 'manual' | 'live'

  // ---- Manual mode state ----
  const [houses, setHouses] = useState(initialHouses)
  const [results, setResults] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const updateHouse = (index, field, value) => {
    const updated = [...houses]
    updated[index] = { ...updated[index], [field]: parseFloat(value) || 0 }
    setHouses(updated)
  }

  const runAllocation = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('http://127.0.0.1:8000/nanogrids/allocate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ houses }),
      })
      if (!res.ok) throw new Error(`Server returned ${res.status}`)
      const data = await res.json()
      setResults(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const resultFor = (id) => results?.find((r) => r.id === id)

  // ---- Live mode state ----
  const [liveData, setLiveData] = useState({})
  const [liveResults, setLiveResults] = useState({})
  const [liveReported, setLiveReported] = useState([])
  const [liveAge, setLiveAge] = useState({})
  const [staleAfter, setStaleAfter] = useState(15)
  const [liveError, setLiveError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [history, setHistory] = useState([])
  const pollRef = useRef(null)

  useEffect(() => {
    if (mode !== 'live') {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }

    const poll = async () => {
      try {
        const res = await fetch('http://127.0.0.1:8000/houses')
        if (!res.ok) throw new Error(`Server returned ${res.status}`)
        const data = await res.json()
        setLiveData(data.data || {})
        setLiveResults(data.results || {})
        setLiveReported(data.reported || [])
        setLiveAge(data.age_s || {})
        setStaleAfter(data.stale_after_s || 15)
        setLiveError(null)
        setLastUpdated(new Date())
        const r = data.results || {}
        setHistory((prev) =>
          [
            ...prev,
            {
              time: new Date().toLocaleTimeString(),
              H1: r.H1?.P_alloc,
              H2: r.H2?.P_alloc,
              H3: r.H3?.P_alloc,
              H4: r.H4?.P_alloc,
              H1_PG: data.data?.H1?.P_G,
              H1_PD: data.data?.H1?.P_D,
              H1_discharge: r.H1?.P_discharge_max,
              H1_charge: r.H1?.P_charge_max,
              H1_soc: data.data?.H1?.soc_pct,
            },
          ].slice(-20),
        )
      } catch (err) {
        setLiveError(err.message)
      }
    }

    poll() // fetch immediately on entering live mode
    pollRef.current = setInterval(poll, 3000) // then every 3 seconds

    return () => clearInterval(pollRef.current)
  }, [mode])

  return (
    <div className="hub-container">
      <h1>Nanogrid Central Hub</h1>

      <div className="mode-toggle">
        <button
          className={mode === 'manual' ? 'mode-btn active' : 'mode-btn'}
          onClick={() => setMode('manual')}
        >
          Manual Test
        </button>
        <button
          className={mode === 'live' ? 'mode-btn active' : 'mode-btn'}
          onClick={() => setMode('live')}
        >
          Live Hub
        </button>
      </div>

      {mode === 'manual' && (
        <>
          <p className="subtitle">Enter each house's generation, demand, battery availability, and cost.</p>

          <div className="house-grid">
            {houses.map((house, index) => {
              const result = resultFor(house.id)
              return (
                <div key={house.id} className="house-card">
                  <div className="house-card-header">
                    <h2>{house.id}</h2>
                  </div>

                  <div className="house-inputs">
                    <label>
                      P_G (W)
                      <input
                        type="number"
                        value={house.P_G}
                        onChange={(e) => updateHouse(index, 'P_G', e.target.value)}
                      />
                    </label>

                    <label>
                      P_D (W)
                      <input
                        type="number"
                        value={house.P_D}
                        onChange={(e) => updateHouse(index, 'P_D', e.target.value)}
                      />
                    </label>

                    <label>
                      Battery SOC (%)
                      <input
                        type="number"
                        min="0"
                        max="100"
                        value={house.soc_pct}
                        onChange={(e) => updateHouse(index, 'soc_pct', e.target.value)}
                      />
                    </label>

                    <label>
                      Capacity (Wh)
                      <input
                        type="number"
                        value={house.capacity_Wh}
                        onChange={(e) => updateHouse(index, 'capacity_Wh', e.target.value)}
                      />
                    </label>

                    <label>
                      Cost (C)
                      <input
                        type="number"
                        step="0.01"
                        value={house.C}
                        onChange={(e) => updateHouse(index, 'C', e.target.value)}
                      />
                    </label>
                  </div>

                  {result && (
                    <div className="house-result">
                      <div>
                        <span className="result-label">Surplus</span>
                        <span className="result-val">{result.P_surplus.toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Drawn from battery</span>
                        <span className="result-val">{result.P_alloc.toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Received</span>
                        <span className="result-val">{(result.P_recv ?? 0).toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Stored in battery</span>
                        <span className="result-val">{(result.P_stored ?? 0).toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Local deficit</span>
                        <span className="result-val">{result.P_local_deficit.toFixed(2)} W</span>
                      </div>
                    </div>
                  )}
                  <BatteryBlock result={result} />
                </div>
              )
            })}
          </div>

          <button className="run-btn" onClick={runAllocation} disabled={loading}>
            {loading ? 'Running...' : 'Run Allocation'}
          </button>

          {error && <p className="error">Error: {error}</p>}
        </>
      )}

      {mode === 'live' && (
        <>
          <div className="live-meta">
            <span className={liveReported.length >= 4 ? 'status-dot live' : 'status-dot'} />
            <p className="subtitle">
              Showing real data reported by House Arduinos. Refreshing every 3 seconds.
              {lastUpdated && (
                <span className="timestamp">Last updated: {lastUpdated.toLocaleTimeString()}</span>
              )}
            </p>
          </div>

          {liveError && <p className="error">Error: {liveError}</p>}

          <div className="house-grid">
            {HOUSE_IDS.map((id) => {
              const data = liveData[id]
              const result = liveResults[id]
              const hasReported = liveReported.includes(id)
              const isDummy = data?.source === 'dummy'
              const age = liveAge[id]
              const isStale = hasReported && !isDummy && age !== undefined && age > staleAfter

              return (
                <div key={id} className="house-card">
                  <div className="house-card-header">
                    <h2>{id}</h2>
                    <span className="card-tags">
                      {isDummy && <span className="tag dummy">dummy</span>}
                      {isStale && <span className="tag stale">no data {age?.toFixed(0)}s</span>}
                      <span className={hasReported && !isStale ? 'status-dot live' : 'status-dot'} />
                    </span>
                  </div>

                  {!hasReported && <div className="waiting">Waiting for data...</div>}

                  {data && (
                    <div className="live-readings">
                      <div>
                        <span className="result-label">P_G</span>
                        <span className="result-val">{data.P_G.toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">P_D</span>
                        <span className="result-val">{data.P_D.toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Cost</span>
                        <span className="result-val">{data.C}</span>
                      </div>
                      {data.rtc && (
                        <div>
                          <span className="result-label">RTC</span>
                          <span className="result-val">{data.rtc}</span>
                        </div>
                      )}
                      {data.loads && Object.entries(data.loads).map(([name, w]) => (
                        <div key={name}>
                          <span className="result-label">Load {name}</span>
                          <span className="result-val">{Number(w).toFixed(1)} W</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {result && (
                    <div className="house-result">
                      <div>
                        <span className="result-label">Surplus</span>
                        <span className="result-val">{result.P_surplus.toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Drawn from battery</span>
                        <span className="result-val">{result.P_alloc.toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Received</span>
                        <span className="result-val">{(result.P_recv ?? 0).toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Stored in battery</span>
                        <span className="result-val">{(result.P_stored ?? 0).toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Local deficit</span>
                        <span className="result-val">{result.P_local_deficit.toFixed(2)} W</span>
                      </div>
                    </div>
                  )}

                  <BatteryBlock result={result} />

                  {hasReported && !result && (
                    <div className="waiting">Waiting for all 4 houses to report...</div>
                  )}
                </div>
              )
            })}
          </div>

          <div className="history-chart">
            <h2>Allocation History</h2>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={history} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#2e303a" strokeDasharray="3 3" />
                <XAxis dataKey="time" stroke="#9ca3af" fontSize={12} tickMargin={8} />
                <YAxis stroke="#9ca3af" fontSize={12} tickMargin={8} />
                <Tooltip
                  contentStyle={{
                    background: '#1b1d24',
                    border: '1px solid #2e303a',
                    borderRadius: 10,
                    color: '#f3f4f6',
                  }}
                  labelStyle={{ color: '#f3f4f6' }}
                />
                <Legend />
                <Line type="monotone" dataKey="H1" stroke="#c084fc" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="H2" stroke="#4ade80" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="H3" stroke="#fbbf24" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="H4" stroke="#38bdf8" dot={false} strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="history-chart">
            <h2>House 1: generation, demand and battery limits</h2>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={history} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#2e303a" strokeDasharray="3 3" />
                <XAxis dataKey="time" stroke="#9ca3af" fontSize={12} tickMargin={8} />
                <YAxis stroke="#9ca3af" fontSize={12} tickMargin={8} unit=" W" />
                <Tooltip
                  contentStyle={{ background: '#1b1d24', border: '1px solid #2e303a', borderRadius: 10, color: '#f3f4f6' }}
                  labelStyle={{ color: '#f3f4f6' }}
                />
                <Legend />
                <Line type="monotone" dataKey="H1_PG" name="Generated" stroke="#4ade80" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="H1_PD" name="Demand" stroke="#f87171" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="H1_discharge" name="Can discharge" stroke="#fbbf24" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="H1_charge" name="Can charge" stroke="#38bdf8" dot={false} strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  )
}

export default App