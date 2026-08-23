import { useEffect, useState } from 'react'
import { buildEbayTitle, EBAY_TITLE_MAX } from '../lib/ebayTitle.js'
import { formatCompPrice, formatCompRange, spreadWarning, summarizeComps } from '../lib/compStats.js'

const FIELDS = [
  { key: 'player_name', label: 'Player', type: 'text', wide: true },
  { key: 'year', label: 'Year', type: 'number' },
  { key: 'brand', label: 'Brand', type: 'text' },
  { key: 'set_name', label: 'Set', type: 'text' },
  { key: 'card_number', label: 'Card #', type: 'text' },
  { key: 'team', label: 'Team', type: 'text' },
  { key: 'parallel_color', label: 'Parallel Color', type: 'text' },
  { key: 'serial_number', label: 'Serial Number (e.g. /99)', type: 'text' },
  { key: 'condition', label: 'Condition', type: 'text' },
  { key: 'quantity', label: 'Quantity', type: 'number', min: '1' },
]

const FLAGS = [
  { key: 'is_rookie', label: 'Rookie' },
  { key: 'is_first_bowman', label: '1st Bowman' },
  { key: 'is_autograph', label: 'Auto' },
  { key: 'is_patch', label: 'Patch' },
  { key: 'is_refractor', label: 'Refractor' },
]

export default function CardForm({ initial, onChange, onSubmit, submitting, comps, suggestedPrice, mock }) {
  const [data, setData] = useState(initial)

  useEffect(() => {
    setData(initial)
  }, [initial])

  // Auto-populate listed price from suggested if user hasn't set one yet.
  useEffect(() => {
    if (suggestedPrice && (data.listed_price === null || data.listed_price === undefined || data.listed_price === '')) {
      const next = { ...data, listed_price: suggestedPrice, suggested_price: suggestedPrice }
      setData(next)
      onChange?.(next)
    }
  }, [suggestedPrice])

  const update = (key, value) => {
    const next = { ...data, [key]: value }
    setData(next)
    onChange?.(next)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    // quantity is non-Optional server-side (default 1, ge=1), but clearing the
    // input stores null mid-edit — coerce at submit so the save can't 422.
    onSubmit?.({ ...data, quantity: data.quantity ?? 1 })
  }

  const preview = buildEbayTitle(data)
  // Suggested price is a median, so the spread it was drawn from is part of
  // reading it — a 10× range usually means variants contaminated the comps.
  const compSummary = summarizeComps(comps)
  const compWarning = spreadWarning(compSummary)

  return (
    <form onSubmit={handleSubmit} className="card-panel space-y-5">
      {mock && (
        <div className="bg-yellow-900/40 border border-yellow-700 text-yellow-200 text-sm rounded-lg px-3 py-2">
          Showing mock data — set <code className="font-mono">ANTHROPIC_API_KEY</code> for real extraction.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {FIELDS.map((f) => (
          <div key={f.key} className={f.wide ? 'md:col-span-2' : ''}>
            <label className="label">{f.label}</label>
            <input
              type={f.type}
              min={f.min}
              value={data[f.key] ?? ''}
              onChange={(e) =>
                update(f.key, f.type === 'number' ? (e.target.value ? Number(e.target.value) : null) : e.target.value)
              }
              className="input"
            />
          </div>
        ))}
      </div>

      <div>
        <label className="label">Flags</label>
        <div className="flex flex-wrap gap-2">
          {FLAGS.map((f) => {
            const active = !!data[f.key]
            return (
              <button
                type="button"
                key={f.key}
                onClick={() => update(f.key, !active)}
                className={`px-4 py-2 rounded-lg font-semibold text-sm transition ${
                  active ? 'bg-emerald-600 text-white' : 'bg-ink-700 text-gray-300 hover:bg-ink-600'
                }`}
              >
                {f.label}
              </button>
            )
          })}
        </div>
      </div>

      {preview.full && (
        <div>
          <div className="flex items-baseline justify-between">
            <label className="label">eBay Title Preview</label>
            <span
              className={`text-xs font-mono ${preview.truncated ? 'text-red-400 font-bold' : 'text-emerald-400'}`}
            >
              {preview.length}/{EBAY_TITLE_MAX}
            </span>
          </div>
          <div className="bg-ink-900 border border-ink-700 rounded-lg px-3 py-2 text-sm font-mono text-gray-200 break-words">
            <span>{preview.title}</span>
            {preview.truncated && (
              <span className="text-red-400 line-through opacity-70">
                {preview.full.slice(preview.title.length)}
              </span>
            )}
          </div>
          {preview.truncated && (
            <p className="text-xs text-red-400 mt-1">
              Over eBay's {EBAY_TITLE_MAX}-character limit — the struck-through part will be cut off.
            </p>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="label">Suggested Price</label>
          <input
            type="number"
            step="0.01"
            value={data.suggested_price ?? ''}
            onChange={(e) => update('suggested_price', e.target.value ? Number(e.target.value) : null)}
            className="input bg-ink-700"
            readOnly
          />
          {compSummary && (
            <p className="text-xs text-gray-500 mt-1">
              Median of {compSummary.count} comp{compSummary.count === 1 ? '' : 's'} spanning{' '}
              <span className={compSummary.wide ? 'text-yellow-400 font-semibold' : 'text-gray-400'}>
                {formatCompRange(compSummary)}
              </span>
            </p>
          )}
        </div>
        <div>
          <label className="label">Your Listed Price (USD)</label>
          <input
            type="number"
            step="0.01"
            min="0"
            value={data.listed_price ?? ''}
            onChange={(e) => update('listed_price', e.target.value ? Number(e.target.value) : null)}
            className="input"
            placeholder="e.g. 12.99"
          />
        </div>
      </div>

      <div>
        <label className="label">Notes</label>
        <textarea
          value={data.notes ?? ''}
          onChange={(e) => update('notes', e.target.value)}
          className="input min-h-[80px]"
          placeholder="Any extra detail you want in the eBay description"
        />
      </div>

      {comps && comps.length > 0 && (
        <div>
          <label className="label">Recent Comps ({comps.length})</label>
          {compWarning && (
            <p className="text-xs text-yellow-400 mb-1.5">{compWarning}</p>
          )}
          <div className="bg-ink-900 border border-ink-700 rounded-lg max-h-48 overflow-y-auto">
            {comps.map((c, idx) => (
              <div key={idx} className="flex justify-between gap-3 px-3 py-2 border-b border-ink-700 last:border-b-0 text-sm">
                <span className="text-gray-300 truncate">{c.title}</span>
                {/* Formatted through the same usable-price test the summary
                    above applies, so the list can't show a price the range
                    excluded — and a null can't render as a confident $0.00. */}
                <span className="text-emerald-400 font-bold whitespace-nowrap">{formatCompPrice(c.price)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <button type="submit" disabled={submitting} className="btn-primary w-full text-lg">
        {submitting ? 'Saving…' : 'Save & Copy Listing for eBay'}
      </button>
      <p className="text-xs text-gray-500 text-center -mt-2">
        Saves the card, copies title + price + description to your clipboard, and opens eBay's sell page in a new tab so you can paste.
      </p>
    </form>
  )
}
