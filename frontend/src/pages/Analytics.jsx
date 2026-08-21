import { useEffect, useRef, useState } from 'react'
import {
  getAnalytics, reassignUser, deleteUserData, getConfiguredUsers,
  downloadBackup, importInventoryCsv, getUploadOrphans, cleanupUploadOrphans,
  getStorageUsage, resyncSheet, getSoldYears, downloadSoldCsv,
} from '../api'
import { formatApiError } from '../lib/apiError.js'

const fmt = (n) => (n ?? 0).toLocaleString()
const usd = (n) => `$${(n ?? 0).toFixed(2)}`
const fmtBytes = (n) => {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB']
  let v = n
  let u = -1
  do { v /= 1024; u += 1 } while (v >= 1024 && u < units.length - 1)
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[u]}`
}

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
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            <Tile label="Est. cost" value={usd(t.est_cost_usd)} />
            <Tile label="Scans" value={fmt(t.scans)} />
            <Tile label="Input tokens" value={fmt(t.input_tokens)} />
            <Tile label="Output tokens" value={fmt(t.output_tokens)} />
            <Tile label="Corrections" value={fmt(t.corrections)} />
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

          <ManageData users={report.users} onDone={() => window.location.reload()} />
        </>
      )}
    </div>
  )
}

function ManageData({ users, onDone }) {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [targets, setTargets] = useState([])
  const [storage, setStorage] = useState(null)
  // Years that actually have sales, so the tax export offers real choices
  // rather than a free-text box that can quietly produce an empty file.
  const [soldYears, setSoldYears] = useState([])
  const [soldYear, setSoldYear] = useState('')

  const loadStorage = () => getStorageUsage().then(setStorage).catch(() => setStorage(null))

  useEffect(() => {
    getConfiguredUsers().then((d) => setTargets(d.users || [])).catch(() => setTargets([]))
    loadStorage()
    getSoldYears()
      .then((d) => {
        const years = d.years || []
        setSoldYears(years)
        // Default to the most recent year with sales — the one a return is
        // almost always being prepared for.
        if (years.length) setSoldYear(String(years[0]))
      })
      .catch(() => setSoldYears([]))
  }, [])

  const merge = async () => {
    if (!from || !to || from === to) { setMsg('Pick two different users.'); return }
    setBusy(true); setMsg('')
    try {
      const r = await reassignUser(from, to)
      const n = r.moved.usage_events + r.moved.scans + r.moved.corrections
      setMsg(`Moved ${n} rows from ${from} to ${to}.`)
      setTimeout(onDone, 1200)
    } catch (e) {
      setMsg(e.response?.data?.detail || 'Merge failed.')
    } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!from) { setMsg('Pick a user to delete.'); return }
    if (!window.confirm(`Delete all analytics data for "${from}"? This cannot be undone.`)) return
    setBusy(true); setMsg('')
    try {
      await deleteUserData(from)
      setMsg(`Deleted ${from}'s data.`)
      setTimeout(onDone, 1200)
    } catch (e) {
      setMsg(e.response?.data?.detail || 'Delete failed.')
    } finally { setBusy(false) }
  }

  const backup = async () => {
    setBusy(true); setMsg('')
    try {
      await downloadBackup()
      setMsg('Backup downloaded.')
    } catch (e) {
      // Show what the server said. A snapshot that fails for want of disk
      // space says so now, and "Backup failed." would swallow the one detail
      // that tells the owner what to do about it.
      setMsg(formatApiError(e, 'Backup failed.'))
    } finally { setBusy(false) }
  }

  const exportSold = async () => {
    setBusy(true); setMsg('')
    try {
      await downloadSoldCsv(soldYear || undefined)
      setMsg(soldYear ? `Sold cards for ${soldYear} downloaded.` : 'All sold cards downloaded.')
    } catch (e) {
      setMsg(formatApiError(e, 'Sold export failed.'))
    } finally { setBusy(false) }
  }

  const fileRef = useRef(null)

  const importCsv = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file
    if (!file) return
    setBusy(true); setMsg('')
    try {
      const r = await importInventoryCsv(file)
      const parts = [`Imported ${r.created} card${r.created === 1 ? '' : 's'}.`]
      if (r.skipped.length) {
        const reasons = r.skipped.slice(0, 3).map((s) => `row ${s.row}: ${s.reason}`).join('; ')
        parts.push(`Skipped ${r.skipped.length}: ${reasons}${r.skipped.length > 3 ? '…' : ''}`)
      }
      if (r.warnings.length) {
        parts.push(r.warnings.slice(0, 3).join('; ') + (r.warnings.length > 3 ? '…' : ''))
      }
      setMsg(parts.join(' '))
      loadStorage()
    } catch (err) {
      const detail = err.response?.data?.detail
      setMsg(typeof detail === 'string' ? detail : 'Import failed.')
    } finally { setBusy(false) }
  }

  const resync = async () => {
    // Destructive: the Inventory tab is cleared and rewritten from the database,
    // so anything typed directly into the sheet is discarded.
    const ok = window.confirm(
      'Rewrite the Google Sheet from the database?\n\n' +
      'The Inventory tab is cleared and rewritten, so anything typed directly ' +
      'into the sheet is discarded. Running it twice is safe — it produces the ' +
      'same result.',
    )
    if (!ok) return
    setBusy(true); setMsg('')
    try {
      const r = await resyncSheet()
      // The repair tool must not fail silently — a silent failure here is what
      // produced the mess it exists to clean up.
      setMsg(r.ok ? `Sheet rewritten: ${r.synced} row${r.synced === 1 ? '' : 's'}.`
                  : r.detail || 'Resync failed.')
    } catch (e) {
      setMsg(e.response?.data?.detail || 'Resync failed.')
    } finally { setBusy(false) }
  }

  const cleanupPhotos = async () => {
    setBusy(true); setMsg('')
    try {
      const o = await getUploadOrphans()
      if (!o.count) {
        setMsg('No orphaned photos to clean up.')
        return
      }
      const mb = (o.bytes / (1024 * 1024)).toFixed(1)
      // Most of the uploads dir flagged at once usually means the cards no
      // longer reference their photos (e.g. inventory restored from CSV,
      // which has no photo columns) — not genuinely abandoned scans.
      const bulk = o.total_files > 0 && o.count >= 10 && o.count / o.total_files >= 0.5
      const ok = window.confirm(
        (bulk
          ? `WARNING: this would delete ${o.count} of the ${o.total_files} photos on the server. ` +
            `That usually means saved cards lost their photo links (e.g. after a CSV import/restore, ` +
            `which does not carry photos) — NOT that the photos are junk. ` +
            `If you recently imported inventory from CSV, cancel and ask before cleaning up.\n\n`
          : '') +
        `Delete ${o.count} orphaned photo${o.count === 1 ? '' : 's'} (${mb} MB)? ` +
        `Photos attached to saved cards or scanned in the last ${o.grace_hours}h are kept.`,
      )
      if (!ok) return
      const r = await cleanupUploadOrphans()
      setMsg(`Deleted ${r.deleted} photo${r.deleted === 1 ? '' : 's'}, freed ${(r.freed_bytes / (1024 * 1024)).toFixed(1)} MB.`)
      loadStorage()
    } catch (e) {
      setMsg(e.response?.data?.detail || 'Cleanup failed.')
    } finally { setBusy(false) }
  }

  return (
    <div className="card-panel">
      <div className="font-bold mb-1">Manage data</div>
      <p className="text-xs text-gray-500 mb-3">
        Merge a stale/renamed username into a real user (keeps its cost history), or delete it.
        Download a database backup regularly — inventory, scans, and usage history all live in it.
      </p>
      {storage && (
        <div className="grid grid-cols-3 gap-3 mb-3">
          <Tile label="Database size" value={fmtBytes(storage.db_bytes)} />
          <Tile label="Photos on server" value={fmt(storage.uploads_count)} />
          <Tile label="Photo storage" value={fmtBytes(storage.uploads_bytes)} />
        </div>
      )}
      <div className="mb-3 flex flex-wrap gap-3">
        <button onClick={backup} disabled={busy} className="btn-secondary">
          Download database backup
        </button>
        <button onClick={() => fileRef.current?.click()} disabled={busy} className="btn-secondary">
          Import inventory CSV
        </button>
        <input ref={fileRef} type="file" accept=".csv,text/csv" onChange={importCsv} className="hidden" />
        <button onClick={cleanupPhotos} disabled={busy} className="btn-secondary">
          Clean up orphaned photos
        </button>
        <button onClick={resync} disabled={busy} className="btn-secondary">
          Resync sheet
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        <strong>Resync sheet</strong> rewrites the Google Sheet's Inventory tab from the
        database — it clears the data rows and writes every card back, so anything typed
        directly into the sheet is discarded. It's safe to run repeatedly (twice in a row
        produces the same sheet), and it's how CSV-imported cards reach the mirror.
      </p>
      <div className="flex flex-wrap items-end gap-3 mb-2">
        <div>
          <label className="label">Sold cards export</label>
          <select
            value={soldYear}
            onChange={(e) => setSoldYear(e.target.value)}
            className="input"
          >
            <option value="">All years</option>
            {soldYears.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <button onClick={exportSold} disabled={busy} className="btn-secondary">
          Download sold CSV
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Sold cards with their sale date and price, ordered oldest first, for tax reporting.
        Sold rows also appear in the full inventory export, but mixed in with everything else
        and with no sale date to sort on. The year list shows only years that have sales.
        Gross proceeds only — the app doesn't record what a card cost you.
      </p>
      <p className="text-xs text-gray-500 mb-3">
        Import expects the CSV export's column layout (columns matched by header name — extra
        columns are ignored, and Parallel / Serial # / Refractor columns are picked up if present).
        Every row creates a new card; the Google Sheets mirror is not updated by imports.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="label">User</label>
          <select value={from} onChange={(e) => setFrom(e.target.value)} className="input">
            <option value="">Select…</option>
            {users.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Merge into</label>
          <select value={to} onChange={(e) => setTo(e.target.value)} className="input">
            <option value="">Select…</option>
            {targets.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <button onClick={merge} disabled={busy} className="btn-secondary">Merge</button>
        <button onClick={remove} disabled={busy}
                className="px-3 py-2 rounded-lg text-sm font-semibold bg-red-900/40 border border-red-700 text-red-200 hover:bg-red-900/60">
          Delete
        </button>
      </div>
      {msg && <div className="text-xs text-gray-400 mt-2">{msg}</div>}
    </div>
  )
}
