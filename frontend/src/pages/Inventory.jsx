import { useEffect, useMemo, useState } from 'react'
import CardTable from '../components/CardTable.jsx'
import { filterCards, isNarrowed, sortCards } from '../lib/sortCards'
import {
  computeInventoryStats,
  copiesHint,
  filteredScopeLabel,
  joinHints,
  overallHint,
} from '../lib/inventoryStats'
import { formatApiError } from '../lib/apiError.js'
import { formatCompPrice, formatCompRange, spreadWarning, summarizeComps } from '../lib/compStats.js'
import { soldAtFromDateInput, todayLocalDate } from '../lib/soldDate.js'
import { listCards, markSold, unmarkSold, attachEbayListing, deleteCard, getEbayListingText, getPricing, updateCard, downloadInventoryCsv } from '../api'

// Shown when the listing text was built for a card that has no price yet.
const NO_PRICE_WARNING = 'This card has no price yet, so the listing text has none either — look up comps before you list it.'

function StatTile({ label, value, hint }) {
  return (
    <div className="card-panel">
      <div className="text-xs uppercase tracking-wide text-gray-400">{label}</div>
      <div className="text-2xl font-black text-gray-100 mt-1">{value}</div>
      {hint ? <div className="text-xs text-gray-500 mt-1">{hint}</div> : null}
    </div>
  )
}

function MarkSoldModal({ card, onClose, onConfirm }) {
  const [price, setPrice] = useState(card.listed_price ?? '')
  const [date, setDate] = useState(todayLocalDate())
  const [saving, setSaving] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      await onConfirm({
        sold_price: Number(price),
        // Null lets the backend stamp its own time rather than sending an
        // Invalid Date; the picker is `required`, so this is the odd path.
        sold_at: soldAtFromDateInput(date),
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
            min="0.01"
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
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    if (!/^https:\/\//i.test(url.trim())) {
      setError('URL must start with https://')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onConfirm({ ebay_listing_id: id, ebay_listing_url: url.trim() })
      onClose()
    } catch (err) {
      setError(formatApiError(err, err.message || 'Failed to attach listing.'))
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
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="input"
            placeholder="https://www.ebay.com/itm/…"
            pattern="https://.*"
            title="Must start with https://"
            required
          />
        </div>
        {error && <div className="text-sm text-red-400 mb-3">{error}</div>}
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
  // "Comps say" is a median; show the spread it came from so a contaminated
  // set is visible before "Set Price to $X" is pressed.
  const compSummary = summarizeComps(result?.comps)
  const compWarning = spreadWarning(compSummary)

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
                {compSummary && (
                  <div className="text-xs text-gray-500 mt-1">
                    {compSummary.count} comp{compSummary.count === 1 ? '' : 's'},{' '}
                    <span className={compSummary.wide ? 'text-yellow-400 font-semibold' : 'text-gray-400'}>
                      {formatCompRange(compSummary)}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {compWarning && <div className="text-xs text-yellow-400 mb-3">{compWarning}</div>}

            {result.comps?.length > 0 && (
              <>
                <div className={`bg-ink-900 border border-ink-700 rounded-lg max-h-40 overflow-y-auto ${result.comps.length > 8 ? 'mb-1' : 'mb-3'}`}>
                  {result.comps.slice(0, 8).map((c, idx) => (
                    <div key={idx} className="flex justify-between gap-3 px-3 py-2 border-b border-ink-700 last:border-b-0 text-sm">
                      <span className="text-gray-300 truncate">{c.title}</span>
                      <span className="text-emerald-400 font-bold whitespace-nowrap">{formatCompPrice(c.price)}</span>
                    </div>
                  ))}
                </div>
                {/* The list is capped at 8 but the median is over all of them —
                    say so, or the range above looks like it disagrees. */}
                {result.comps.length > 8 && (
                  <div className="text-xs text-gray-500 mb-3">
                    Showing 8 of {result.comps.length} — the suggested price uses all of them.
                  </div>
                )}
              </>
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

  const filtered = useMemo(
    () => sortCards(filterCards(cards, { status: statusFilter, search }), sort.key, sort.dir),
    [cards, search, statusFilter, sort],
  )

  const onSort = (key) => {
    setSort((prev) => (
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' }
    ))
  }

  // Copy-aware: a qty-3 row is three cards worth three listed prices.
  //
  // The tiles describe whatever the table below is showing. Computed from the
  // whole collection they answered a question nobody asked while the table
  // showed a subset — there was no way to ask "what are my Bowman autos
  // worth". `overall` stays alongside so a narrowed tile can caption the
  // collection-wide number instead of just looking wrong.
  const narrowed = isNarrowed({ status: statusFilter, search })
  const overall = useMemo(() => computeInventoryStats(cards), [cards])
  const stats = useMemo(
    () => (narrowed ? computeInventoryStats(filtered) : overall),
    [narrowed, filtered, overall],
  )
  const money = (v) => `$${v.toFixed(2)}`

  const onMarkSold = (card) => setSoldModalCard(card)
  const onAttachEbay = (card) => setAttachModalCard(card)

  const onUnmarkSold = async (card) => {
    const label = card.player_name || `card #${card.id}`
    if (!window.confirm(`Unmark ${label} as sold? The card returns to Active and the sale price/date are cleared.`)) return
    try {
      await unmarkSold(card.id)
      await reload()
    } catch (e) {
      alert('Unmark failed: ' + (e.response?.data?.detail || e.message))
    }
  }

  // Quiet clipboard-only variant of the Open eBay flow: no tab, no alert.
  // Returns true so CardTable can flash "Copied ✓" on the row.
  const onCopyText = async (card) => {
    try {
      const text = await getEbayListingText(card.id)
      try {
        await navigator.clipboard.writeText(text.clipboard_text)
        // Quiet by design, with one exception: text copied for a card with no
        // price carries no price, and the paste into eBay is the last moment
        // that is cheap to notice.
        if (text.has_price === false) alert(NO_PRICE_WARNING)
        return true
      } catch {
        // Clipboard API blocked — fall back to a prompt for manual copy.
        window.prompt('Copy this listing text:', text.clipboard_text)
        return false
      }
    } catch {
      alert('Failed to build listing text')
      return false
    }
  }

  const onOpenEbay = async (card) => {
    // Copy listing text to clipboard, then open eBay's sell page.
    // (Pre-fill URLs no longer populate eBay's form — paste workflow only.)
    try {
      const text = await getEbayListingText(card.id)
      try {
        await navigator.clipboard.writeText(text.clipboard_text)
        alert(text.has_price === false
          ? `Listing text copied — paste into eBay after the page opens.\n\n${NO_PRICE_WARNING}`
          : 'Listing text copied to clipboard — paste into eBay after the page opens.')
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
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Inventory</h1>
        {narrowed && (
          <span className="text-xs text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded px-2 py-1">
            {filteredScopeLabel(filtered.length)}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatTile
          label="Total Cards"
          value={stats.total}
          hint={joinHints(copiesHint(stats), narrowed && overallHint(stats.total, overall.total))}
        />
        <StatTile
          label="Listed"
          value={stats.listed}
          hint={narrowed ? overallHint(stats.listed, overall.listed) : null}
        />
        <StatTile
          label="Sold"
          value={stats.sold}
          hint={narrowed ? overallHint(stats.sold, overall.sold) : null}
        />
        <StatTile
          label="Revenue"
          value={money(stats.revenue)}
          hint={narrowed ? overallHint(stats.revenue, overall.revenue, money) : null}
        />
        <StatTile
          label="Est. Active Value"
          value={money(stats.activeValue)}
          hint={narrowed ? overallHint(stats.activeValue, overall.activeValue, money) : null}
        />
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
          onUnmarkSold={onUnmarkSold}
          onAttachEbay={onAttachEbay}
          onOpenEbay={onOpenEbay}
          onDelete={onDelete}
          onCheckComps={setCompsModalCard}
          onCopyText={onCopyText}
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
