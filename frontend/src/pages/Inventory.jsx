import { useEffect, useMemo, useState } from 'react'
import CardTable from '../components/CardTable.jsx'
import { cardMatchesSearch, sortCards } from '../lib/sortCards'
import { listCards, markSold, attachEbayListing, deleteCard, getEbayListingText, getPricing, updateCard, downloadInventoryCsv } from '../api'

function StatTile({ label, value }) {
  return (
    <div className="card-panel">
      <div className="text-xs uppercase tracking-wide text-gray-400">{label}</div>
      <div className="text-2xl font-black text-gray-100 mt-1">{value}</div>
    </div>
  )
}

function MarkSoldModal({ card, onClose, onConfirm }) {
  const [price, setPrice] = useState(card.listed_price ?? '')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [saving, setSaving] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      await onConfirm({
        sold_price: Number(price),
        sold_at: new Date(date).toISOString(),
      })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-20 px-4">
      <form onSubmit={submit} className="card-panel w-full max-w-sm">
        <h2 className="text-xl font-bold mb-4">Mark as Sold</h2>
        <div className="mb-3">
          <label className="label">Sale Price (USD)</label>
          <input
            type="number"
            step="0.01"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="input"
            autoFocus
            required
          />
        </div>
        <div className="mb-5">
          <label className="label">Sold On</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="input"
            required
          />
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
          <button type="submit" disabled={saving} className="btn-primary flex-1">
            {saving ? 'Saving…' : 'Confirm'}
          </button>
        </div>
      </form>
    </div>
  )
}

function AttachEbayModal({ card, onClose, onConfirm }) {
  const [id, setId] = useState('')
  const [url, setUrl] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      await onConfirm({ ebay_listing_id: id, ebay_listing_url: url })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-20 px-4">
      <form onSubmit={submit} className="card-panel w-full max-w-md">
        <h2 className="text-xl font-bold mb-1">Attach eBay Listing</h2>
        <p className="text-sm text-gray-400 mb-4">Paste in the listing ID and URL after you publish on eBay.</p>
        <div className="mb-3">
          <label className="label">Listing ID</label>
          <input value={id} onChange={(e) => setId(e.target.value)} className="input" required />
        </div>
        <div className="mb-5">
          <label className="label">Listing URL</label>
          <input value={url} onChange={(e) => setUrl(e.target.value)} className="input" required />
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
          <button type="submit" disabled={saving} className="btn-primary flex-1">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  )
}

function CompsModal({ card, onClose, onApplyPrice }) {
  const [loading, setLoading] = useState(true)
  const [result, setResult] = useState(null)
  const [applying, setApplying] = useState(false)

  useEffect(() => {
    getPricing({
      player_name: card.player_name,
      year: card.year,
      brand: card.brand,
      set_name: card.set_name,
      card_number: card.card_number,
    })
      .then(setResult)
      .catch(() => setResult({ comps: [], suggested_price: null, source: 'mock', note: 'Pricing lookup failed.' }))
      .finally(() => setLoading(false))
  }, [card])

  const suggested = result?.source !== 'mock' ? result?.suggested_price : null
  const delta = suggested != null && card.listed_price != null ? suggested - card.listed_price : null

  const apply = async () => {
    setApplying(true)
    try {
      await onApplyPrice(suggested)
      onClose()
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-20 px-4">
      <div className="card-panel w-full max-w-md">
        <h2 className="text-xl font-bold mb-1">Current Comps</h2>
        <p className="text-sm text-gray-400 mb-4">
          {[card.year, card.brand, card.set_name, card.player_name, card.card_number && `#${card.card_number}`]
            .filter(Boolean).join(' ')}
        </p>

        {loading ? (
          <div className="text-center text-gray-400 py-8">Looking up sold comps…</div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="bg-ink-900 border border-ink-700 rounded-lg px-3 py-2">
                <div className="text-xs uppercase tracking-wide text-gray-400">Listed at</div>
                <div className="text-lg font-black text-gray-100">
                  {card.listed_price != null ? `$${Number(card.listed_price).toFixed(2)}` : '—'}
                </div>
              </div>
              <div className="bg-ink-900 border border-ink-700 rounded-lg px-3 py-2">
                <div className="text-xs uppercase tracking-wide text-gray-400">Comps say</div>
                <div className="text-lg font-black text-gray-100">
                  {suggested != null ? `$${suggested.toFixed(2)}` : '—'}
                  {delta != null && delta !== 0 && (
                    <span className={`ml-2 text-sm font-bold ${delta > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {delta > 0 ? '▲' : '▼'} ${Math.abs(delta).toFixed(2)}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {result.comps?.length > 0 && (
              <div className="bg-ink-900 border border-ink-700 rounded-lg max-h-40 overflow-y-auto mb-3">
                {result.comps.slice(0, 8).map((c, idx) => (
                  <div key={idx} className="flex justify-between gap-3 px-3 py-2 border-b border-ink-700 last:border-b-0 text-sm">
                    <span className="text-gray-300 truncate">{c.title}</span>
                    <span className="text-emerald-400 font-bold whitespace-nowrap">${Number(c.price).toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
            {result.source && result.source !== 'mock' && (
              <div className="text-xs text-emerald-400 mb-1">Source: {result.source === 'ebay_sold' ? 'eBay sold listings' : result.source}</div>
            )}
            {result.note && <div className="text-xs text-yellow-400 mb-3">{result.note}</div>}

            <div className="flex gap-2 mt-2">
              <button type="button" onClick={onClose} className="btn-secondary flex-1">Close</button>
              {suggested != null && suggested !== card.listed_price && (
                <button type="button" onClick={apply} disabled={applying} className="btn-primary flex-1">
                  {applying ? 'Saving…' : `Set Price to $${suggested.toFixed(2)}`}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default function Inventory() {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [sort, setSort] = useState({ key: 'created_at', dir: 'desc' })
  const [soldModalCard, setSoldModalCard] = useState(null)
  const [attachModalCard, setAttachModalCard] = useState(null)
  const [compsModalCard, setCompsModalCard] = useState(null)

  const reload = async () => {
    setLoading(true)
    try {
      const data = await listCards()
      setCards(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  const filtered = useMemo(() => {
    const visible = cards.filter((c) => {
      if (statusFilter && c.status !== statusFilter) return false
      return cardMatchesSearch(c, search)
    })
    return sortCards(visible, sort.key, sort.dir)
  }, [cards, search, statusFilter, sort])

  const onSort = (key) => {
    setSort((prev) => (
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' }
    ))
  }

  const stats = useMemo(() => {
    const total = cards.length
    const listed = cards.filter((c) => c.status === 'active').length
    const sold = cards.filter((c) => c.status === 'sold').length
    const revenue = cards.reduce((sum, c) => sum + (c.sold_price || 0), 0)
    const activeValue = cards
      .filter((c) => c.status === 'active')
      .reduce((sum, c) => sum + (c.listed_price || 0), 0)
    return { total, listed, sold, revenue, activeValue }
  }, [cards])

  const onMarkSold = (card) => setSoldModalCard(card)
  const onAttachEbay = (card) => setAttachModalCard(card)

  const onOpenEbay = async (card) => {
    // Copy listing text to clipboard, then open eBay's sell page.
    // (Pre-fill URLs no longer populate eBay's form — paste workflow only.)
    try {
      const text = await getEbayListingText(card.id)
      try {
        await navigator.clipboard.writeText(text.clipboard_text)
        alert('Listing text copied to clipboard — paste into eBay after the page opens.')
      } catch {
        // Clipboard API blocked — fall back to showing the text in a prompt for manual copy.
        window.prompt('Copy this listing text to paste into eBay:', text.clipboard_text)
      }
      window.open('https://www.ebay.com/sl/sell', '_blank', 'noopener')
    } catch {
      alert('Failed to build listing text')
    }
  }

  const onDelete = async (card) => {
    const label = card.player_name || `card #${card.id}`
    if (!window.confirm(`Permanently delete ${label}? This cannot be undone.`)) return
    try {
      await deleteCard(card.id)
      await reload()
    } catch (e) {
      alert('Delete failed: ' + (e.response?.data?.detail || e.message))
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Inventory</h1>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatTile label="Total Cards" value={stats.total} />
        <StatTile label="Listed" value={stats.listed} />
        <StatTile label="Sold" value={stats.sold} />
        <StatTile label="Revenue" value={`$${stats.revenue.toFixed(2)}`} />
        <StatTile label="Est. Active Value" value={`$${stats.activeValue.toFixed(2)}`} />
      </div>

      <div className="flex flex-col md:flex-row gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search player, team, brand, set, card #…"
          className="input md:max-w-md"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input md:max-w-xs"
        >
          <option value="">All statuses</option>
          <option value="unlisted">Unlisted</option>
          <option value="active">Active</option>
          <option value="sold">Sold</option>
        </select>
        <button onClick={reload} className="btn-secondary md:ml-auto">Refresh</button>
        <button
          onClick={() => downloadInventoryCsv().catch(() => alert('Export failed — try again.'))}
          className="btn-secondary"
        >
          Export CSV
        </button>
      </div>

      {loading ? (
        <div className="card-panel text-center text-gray-400 py-12">Loading…</div>
      ) : (
        <CardTable
          cards={filtered}
          onMarkSold={onMarkSold}
          onAttachEbay={onAttachEbay}
          onOpenEbay={onOpenEbay}
          onDelete={onDelete}
          onCheckComps={setCompsModalCard}
          sort={sort}
          onSort={onSort}
        />
      )}

      {compsModalCard && (
        <CompsModal
          card={compsModalCard}
          onClose={() => setCompsModalCard(null)}
          onApplyPrice={async (price) => {
            await updateCard(compsModalCard.id, { listed_price: price })
            await reload()
          }}
        />
      )}

      {soldModalCard && (
        <MarkSoldModal
          card={soldModalCard}
          onClose={() => setSoldModalCard(null)}
          onConfirm={async (payload) => {
            await markSold(soldModalCard.id, payload)
            await reload()
          }}
        />
      )}

      {attachModalCard && (
        <AttachEbayModal
          card={attachModalCard}
          onClose={() => setAttachModalCard(null)}
          onConfirm={async (payload) => {
            await attachEbayListing(attachModalCard.id, payload)
            await reload()
          }}
        />
      )}
    </div>
  )
}
