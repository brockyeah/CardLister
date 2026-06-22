import { useEffect, useMemo, useState } from 'react'
import CardTable from '../components/CardTable.jsx'
import { listCards, markSold, attachEbayListing, deleteCard, getEbayListingText } from '../api'

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

export default function Inventory() {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [soldModalCard, setSoldModalCard] = useState(null)
  const [attachModalCard, setAttachModalCard] = useState(null)

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
    const s = search.trim().toLowerCase()
    return cards.filter((c) => {
      if (statusFilter && c.status !== statusFilter) return false
      if (s && !(c.player_name || '').toLowerCase().includes(s)) return false
      return true
    })
  }, [cards, search, statusFilter])

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
          placeholder="Search by player name…"
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
