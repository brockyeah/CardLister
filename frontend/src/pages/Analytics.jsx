import { useEffect, useState } from 'react'
import { getAnalytics } from '../api'

const fmt = (n) => (n ?? 0).toLocaleString()
const usd = (n) => `$${(n ?? 0).toFixed(2)}`

const RANGES = [
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' },
  { key: 'month', label: 'This month' },
  { key: 'all', label: 'All time' },
]

function Tile({ label, value }) {
  return (
    <div className="card-panel">
      <div className="text-xs text-gray-400 uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-black text-emerald-400 mt-1">{value}</div>
    </div>
  )
}

export default function Analytics() {
  const [range, setRange] = useState('month')
  const [user, setUser] = useState('')
  const [model, setModel] = useState('')
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    getAnalytics({ range, user: user || undefined, model: model || undefined })
      .then(setReport)
      .catch((e) => setError(e.response?.data?.detail || 'Could not load analytics.'))
      .finally(() => setLoading(false))
  }, [range, user, model])

  const t = report?.totals
  const maxDayCost = Math.max(0.0001, ...(report?.by_day || []).map((d) => d.est_cost_usd))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-1">Analytics</h1>
        <p className="text-gray-400 text-sm">
          API usage and estimated cost. Filter by time, user, and model. Settle shared costs offline.
        </p>
      </div>

      {/* Filters */}
      <div className="card-panel space-y-3">
        <div className="flex flex-wrap gap-2">
          {RANGES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={`px-3 py-1.5 rounded-lg text-sm font-semibold transition ${
                range === r.key ? 'bg-emerald-600 text-white' : 'bg-ink-700 text-gray-300 hover:bg-ink-600'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          <div>
            <label className="label">User</label>
            <select value={user} onChange={(e) => setUser(e.target.value)} className="input">
              <option value="">All users</option>
              {(report?.users || []).map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Model</label>
            <select value={model} onChange={(e) => setModel(e.target.value)} className="input">
              <option value="">All models</option>
              {(report?.models || []).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-200 rounded-lg px-4 py-3">{error}</div>
      )}
      {loading && <div className="text-gray-400 text-sm">Loading…</div>}

      {report && !loading && (
        <>
          {/* Summary tiles */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Tile label="Est. cost" value={usd(t.est_cost_usd)} />
            <Tile label="Scans" value={fmt(t.scans)} />
            <Tile label="Input tokens" value={fmt(t.input_tokens)} />
            <Tile label="Output tokens" value={fmt(t.output_tokens)} />
          </div>

          {t.scans === 0 ? (
            <div className="card-panel text-gray-400 text-sm">No scans match these filters.</div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* By user */}
              <div className="card-panel">
                <div className="font-bold mb-3">By user</div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-400 border-b border-ink-700">
                      <th className="py-2 pr-4 font-semibold">User</th>
                      <th className="py-2 pr-4 font-semibold text-right">Scans</th>
                      <th className="py-2 font-semibold text-right">Est. cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.by_user.map((r) => (
                      <tr key={r.username} className="border-b border-ink-700 last:border-b-0">
                        <td className="py-2 pr-4 text-gray-200">{r.username}</td>
                        <td className="py-2 pr-4 text-right text-gray-300">{fmt(r.scans)}</td>
                        <td className="py-2 text-right text-emerald-400 font-bold">{usd(r.est_cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* By model */}
              <div className="card-panel">
                <div className="font-bold mb-3">By model</div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-400 border-b border-ink-700">
                      <th className="py-2 pr-4 font-semibold">Model</th>
                      <th className="py-2 pr-4 font-semibold text-right">Scans</th>
                      <th className="py-2 font-semibold text-right">Est. cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.by_model.map((r) => (
                      <tr key={r.model} className="border-b border-ink-700 last:border-b-0">
                        <td className="py-2 pr-4 text-gray-200 font-mono text-xs">{r.model}</td>
                        <td className="py-2 pr-4 text-right text-gray-300">{fmt(r.scans)}</td>
                        <td className="py-2 text-right text-emerald-400 font-bold">{usd(r.est_cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* By day */}
          {report.by_day.length > 0 && (
            <div className="card-panel">
              <div className="font-bold mb-3">By day</div>
              <div className="space-y-1.5">
                {report.by_day.map((d) => (
                  <div key={d.date} className="flex items-center gap-3 text-sm">
                    <span className="text-gray-400 font-mono text-xs w-24 flex-shrink-0">{d.date}</span>
                    <div className="flex-1 bg-ink-900 rounded h-4 overflow-hidden">
                      <div
                        className="bg-emerald-600 h-full"
                        style={{ width: `${(d.est_cost_usd / maxDayCost) * 100}%` }}
                      />
                    </div>
                    <span className="text-gray-300 w-16 text-right">{usd(d.est_cost_usd)}</span>
                    <span className="text-gray-500 w-16 text-right text-xs">{fmt(d.scans)} scan{d.scans === 1 ? '' : 's'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <p className="text-xs text-gray-500">
            Costs are estimated from Anthropic's per-token prices (output includes thinking tokens) and may differ
            slightly from your actual invoice. Scans only — eBay comp lookups don't use the API.
          </p>
        </>
      )}
    </div>
  )
}
