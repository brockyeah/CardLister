import StatusBadge from './StatusBadge.jsx'

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

export default function CardTable({ cards, onMarkSold, onAttachEbay, onOpenEbay, onDelete }) {
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
            <th className="px-3 py-3"></th>
            <th className="px-3 py-3">Player</th>
            <th className="px-3 py-3">Year</th>
            <th className="px-3 py-3">Brand</th>
            <th className="px-3 py-3">Set</th>
            <th className="px-3 py-3">Card #</th>
            <th className="px-3 py-3">Cond</th>
            <th className="px-3 py-3 text-right">Qty</th>
            <th className="px-3 py-3 text-right">Listed</th>
            <th className="px-3 py-3">Status</th>
            <th className="px-3 py-3">eBay</th>
            <th className="px-3 py-3">Added</th>
            <th className="px-3 py-3"></th>
          </tr>
        </thead>
        <tbody>
          {cards.map((c) => (
            <tr key={c.id} className="border-t border-ink-700 hover:bg-ink-700/40">
              <td className="px-3 py-2">
                {c.image_path ? (
                  <img src={c.image_path} alt="" className="w-10 h-14 object-cover rounded" />
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
                {c.ebay_listing_url ? (
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
    </div>
  )
}
