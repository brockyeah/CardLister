import { useEffect, useState } from 'react'
import StatusBadge from './StatusBadge.jsx'

// Defense in depth: the backend now rejects non-http(s) listing URLs at save
// time, but this guards rows saved before that validation existed.
const isSafeHttpUrl = (url) => /^https?:\/\//i.test(url || '')

function ImageLightbox({ card, onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const images = [
    { src: card.image_path, label: 'Front' },
    { src: card.back_image_path, label: 'Back' },
  ].filter((img) => img.src)

  return (
    <div
      className="fixed inset-0 bg-black/80 flex items-center justify-center z-30 px-4 cursor-zoom-out"
      onClick={onClose}
    >
      <div className="flex flex-col md:flex-row gap-4 max-h-[90vh] overflow-auto">
        {images.map((img) => (
          <figure key={img.label} className="text-center">
            <img
              src={img.src}
              alt={`${card.player_name || 'Card'} — ${img.label.toLowerCase()}`}
              className="max-h-[80vh] max-w-full object-contain rounded-lg"
            />
            {images.length > 1 && (
              <figcaption className="text-xs text-gray-400 mt-2">{img.label}</figcaption>
            )}
          </figure>
        ))}
      </div>
    </div>
  )
}

function fmtMoney(v) {
  if (v === null || v === undefined || v === '') return '—'
  return `$${Number(v).toFixed(2)}`
}

function fmtDate(v) {
  if (!v) return '—'
  try {
    return new Date(v).toLocaleDateString()
  } catch {
    return v
  }
}

const COLUMNS = [
  { label: '', key: null },
  { label: 'Player', key: 'player_name' },
  { label: 'Year', key: 'year' },
  { label: 'Brand', key: 'brand' },
  { label: 'Set', key: 'set_name' },
  { label: 'Card #', key: 'card_number' },
  { label: 'Cond', key: 'condition' },
  { label: 'Qty', key: 'quantity', right: true },
  { label: 'Listed', key: 'listed_price', right: true },
  { label: 'Status', key: 'status' },
  { label: 'eBay', key: null },
  { label: 'Added', key: 'created_at' },
  { label: '', key: null },
]

export default function CardTable({ cards, onMarkSold, onAttachEbay, onOpenEbay, onDelete, onCheckComps, sort, onSort }) {
  const [lightboxCard, setLightboxCard] = useState(null)

  if (!cards.length) {
    return (
      <div className="card-panel text-center text-gray-400 py-12">
        No cards match. Scan one on the home page to get started.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto card-panel p-0">
      <table className="min-w-full text-sm">
        <thead className="bg-ink-700 text-gray-300 text-left">
          <tr>
            {COLUMNS.map((col, idx) => (
              <th key={idx} className={`px-3 py-3 ${col.right ? 'text-right' : ''}`}>
                {col.key && onSort ? (
                  <button
                    type="button"
                    onClick={() => onSort(col.key)}
                    className="font-semibold hover:text-gray-100 whitespace-nowrap"
                    title={`Sort by ${col.label}`}
                  >
                    {col.label}
                    {sort?.key === col.key && (
                      <span className="ml-1 text-emerald-400">{sort.dir === 'asc' ? '▲' : '▼'}</span>
                    )}
                  </button>
                ) : (
                  col.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cards.map((c) => (
            <tr key={c.id} className="border-t border-ink-700 hover:bg-ink-700/40">
              <td className="px-3 py-2">
                {c.image_path ? (
                  <button
                    type="button"
                    onClick={() => setLightboxCard(c)}
                    className="cursor-zoom-in"
                    title="View full-size photo"
                  >
                    <img src={c.image_path} alt="" className="w-10 h-14 object-cover rounded" />
                  </button>
                ) : (
                  <div className="w-10 h-14 bg-ink-700 rounded" />
                )}
              </td>
              <td className="px-3 py-2 font-semibold text-gray-100">
                {c.player_name || '—'}
                {c.is_first_bowman && (
                  <span className="ml-2 align-middle text-[10px] font-bold uppercase tracking-wide bg-emerald-500/15 text-emerald-400 border border-emerald-500/40 rounded px-1.5 py-0.5">
                    1st
                  </span>
                )}
              </td>
              <td className="px-3 py-2">{c.year || '—'}</td>
              <td className="px-3 py-2">{c.brand || '—'}</td>
              <td className="px-3 py-2">{c.set_name || '—'}</td>
              <td className="px-3 py-2">{c.card_number || '—'}</td>
              <td className="px-3 py-2">{c.condition || '—'}</td>
              <td className="px-3 py-2 text-right">{c.quantity ?? 1}</td>
              <td className="px-3 py-2 text-right">{fmtMoney(c.listed_price)}</td>
              <td className="px-3 py-2"><StatusBadge status={c.status} /></td>
              <td className="px-3 py-2">
                {c.ebay_listing_url && isSafeHttpUrl(c.ebay_listing_url) ? (
                  <a
                    href={c.ebay_listing_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-emerald-400 underline"
                  >
                    View
                  </a>
                ) : (
                  <button
                    onClick={() => onOpenEbay?.(c)}
                    className="text-blue-400 underline text-xs"
                  >
                    Open eBay
                  </button>
                )}
              </td>
              <td className="px-3 py-2 text-gray-400">{fmtDate(c.created_at)}</td>
              <td className="px-3 py-2 whitespace-nowrap">
                {c.status !== 'sold' && (
                  <button
                    onClick={() => onCheckComps?.(c)}
                    className="text-xs bg-emerald-700 hover:bg-emerald-600 text-white rounded px-2 py-1 mr-1"
                    title="Look up current sold comps for this card"
                  >
                    Comps
                  </button>
                )}
                {c.status !== 'sold' && (
                  <button
                    onClick={() => onMarkSold?.(c)}
                    className="text-xs bg-blue-600 hover:bg-blue-500 text-white rounded px-2 py-1 mr-1"
                  >
                    Mark Sold
                  </button>
                )}
                {!c.ebay_listing_id && (
                  <button
                    onClick={() => onAttachEbay?.(c)}
                    className="text-xs bg-ink-600 hover:bg-ink-500 text-white rounded px-2 py-1 mr-1"
                  >
                    Attach eBay ID
                  </button>
                )}
                <button
                  onClick={() => onDelete?.(c)}
                  className="text-xs bg-red-700 hover:bg-red-600 text-white rounded px-2 py-1"
                  title="Permanently delete this card"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {lightboxCard && (
        <ImageLightbox card={lightboxCard} onClose={() => setLightboxCard(null)} />
      )}
    </div>
  )
}
