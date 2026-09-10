import { useState, useEffect, useRef } from 'react'
import './App.css'

const initialHouses = [
  { id: 'H1', P_G: 100, P_D: 120, P_avail: 20, C: 0.5 },
  { id: 'H2', P_G: 90, P_D: 100, P_avail: 15, C: 0.3 },
  { id: 'H3', P_G: 80, P_D: 90, P_avail: 10, C: 0.4 },
  { id: 'H4', P_G: 70, P_D: 75, P_avail: 5, C: 0.6 },
]

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
  const [liveError, setLiveError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
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
        setLiveError(null)
        setLastUpdated(new Date())
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
                      P_avail (W)
                      <input
                        type="number"
                        value={house.P_avail}
                        onChange={(e) => updateHouse(index, 'P_avail', e.target.value)}
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
                        <span className="result-label">Allocated</span>
                        <span className="result-val">{result.P_alloc.toFixed(2)} W</span>
                      </div>
                      {result.P_surplus > 0 ? (
                        <div className="deficit-moot">
                          Local deficit: {result.P_local_deficit.toFixed(2)} W (moot — surplus covers demand, battery not used)
                        </div>
                      ) : (
                        <div>
                          <span className="result-label">Local deficit</span>
                          <span className="result-val">{result.P_local_deficit.toFixed(2)} W</span>
                        </div>
                      )}
                    </div>
                  )}
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

              return (
                <div key={id} className="house-card">
                  <div className="house-card-header">
                    <h2>{id}</h2>
                    <span className={hasReported ? 'status-dot live' : 'status-dot'} />
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
                        <span className="result-label">P_avail</span>
                        <span className="result-val">{data.P_avail.toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Cost</span>
                        <span className="result-val">{data.C}</span>
                      </div>
                    </div>
                  )}

                  {result && (
                    <div className="house-result">
                      <div>
                        <span className="result-label">Surplus</span>
                        <span className="result-val">{result.P_surplus.toFixed(2)} W</span>
                      </div>
                      <div>
                        <span className="result-label">Allocated</span>
                        <span className="result-val">{result.P_alloc.toFixed(2)} W</span>
                      </div>
                      {result.P_surplus > 0 ? (
                        <div className="deficit-moot">
                          Local deficit: {result.P_local_deficit.toFixed(2)} W (moot — surplus covers demand, battery not used)
                        </div>
                      ) : (
                        <div>
                          <span className="result-label">Local deficit</span>
                          <span className="result-val">{result.P_local_deficit.toFixed(2)} W</span>
                        </div>
                      )}
                    </div>
                  )}

                  {hasReported && !result && (
                    <div className="waiting">Waiting for all 4 houses to report...</div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

export default App