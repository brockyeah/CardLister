import { useEffect, useState } from 'react'
import { getUsage } from '../api'

const fmt = (n) => n.toLocaleString()
const usd = (n) => `$${n.toFixed(2)}`

export default function Usage() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getUsage()
      .then(setReport)
      .catch((e) => setError(e.response?.data?.detail || 'Could not load usage.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-1">Usage &amp; Cost Split</h1>
        <p className="text-gray-400 text-sm">
          Estimated Anthropic API cost per user{report ? ` for ${report.period}` : ''}. Settle up offline.
        </p>
      </div>

      {loading && <div className="text-gray-400 text-sm">Loading…</div>}

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-200 rounded-lg px-4 py-3">{error}</div>
      )}

      {report && !loading && (
        <div className="card-panel">
          {report.rows.length === 0 ? (
            <div className="text-gray-400 text-sm">No scans recorded this month yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-ink-700">
                    <th className="py-2 pr-4 font-semibold">User</th>
                    <th className="py-2 pr-4 font-semibold text-right">Scans</th>
                    <th className="py-2 pr-4 font-semibold text-right">Input tokens</th>
                    <th className="py-2 pr-4 font-semibold text-right">Output tokens</th>
                    <th className="py-2 font-semibold text-right">Est. cost</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((r) => (
                    <tr key={r.username} className="border-b border-ink-700 last:border-b-0">
                      <td className="py-2 pr-4 font-medium text-gray-200">{r.username}</td>
                      <td className="py-2 pr-4 text-right text-gray-300">{fmt(r.scans)}</td>
                      <td className="py-2 pr-4 text-right text-gray-300">{fmt(r.input_tokens)}</td>
                      <td className="py-2 pr-4 text-right text-gray-300">{fmt(r.output_tokens)}</td>
                      <td className="py-2 text-right text-emerald-400 font-bold">{usd(r.est_cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-ink-600">
                    <td className="py-2 pr-4 font-bold text-gray-200" colSpan={4}>Total</td>
                    <td className="py-2 text-right font-bold text-emerald-300">{usd(report.total_cost_usd)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          <p className="text-xs text-gray-500 mt-4">
            Costs are estimated from Anthropic's per-token prices (output includes thinking tokens) and may differ
            slightly from your actual invoice. Pricing/scan only — eBay comp lookups don't use the API.
          </p>
        </div>
      )}
    </div>
  )
}
