import { useEffect, useState } from 'react'

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
]

const FLAGS = [
  { key: 'is_rookie', label: 'Rookie' },
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestedPrice])

  const update = (key, value) => {
    const next = { ...data, [key]: value }
    setData(next)
    onChange?.(next)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit?.(data)
  }

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
        </div>
        <div>
          <label className="label">Your Listed Price (USD)</label>
          <input
            type="number"
            step="0.01"
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
          <div className="bg-ink-900 border border-ink-700 rounded-lg max-h-48 overflow-y-auto">
            {comps.map((c, idx) => (
              <div key={idx} className="flex justify-between gap-3 px-3 py-2 border-b border-ink-700 last:border-b-0 text-sm">
                <span className="text-gray-300 truncate">{c.title}</span>
                <span className="text-emerald-400 font-bold whitespace-nowrap">${c.price.toFixed(2)}</span>
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
