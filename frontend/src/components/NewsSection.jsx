import { useEffect, useState } from 'react'
import { getNews } from '../api'

const KEY = 'cardlister_news_open'

export default function NewsSection() {
  const [data, setData] = useState(null)
  const [open, setOpen] = useState(() => localStorage.getItem(KEY) !== '0')

  useEffect(() => {
    getNews().then(setData).catch(() => setData({ callups: [], articles: [] }))
  }, [])

  const toggle = () => {
    const next = !open
    setOpen(next)
    localStorage.setItem(KEY, next ? '1' : '0')
  }

  // Render nothing until we have content — no empty error box.
  if (!data || (data.callups.length === 0 && data.articles.length === 0)) return null

  return (
    <div className="card-panel">
      <button onClick={toggle} className="w-full flex items-center justify-between text-left">
        <span className="label mb-0">Prospect news &amp; call-ups</span>
        <span className="text-gray-400 text-sm">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          {data.callups.length > 0 && (
            <div className="space-y-1.5">
              {data.callups.map((c, i) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <span className="text-gray-500 font-mono text-xs w-20 flex-shrink-0">{c.date}</span>
                  <span className="text-gray-200 font-medium">{c.player_name}</span>
                  <span className="text-gray-400">· {c.to_team}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${c.type_desc === 'Selected' ? 'bg-emerald-700/40 text-emerald-300' : 'bg-ink-700 text-gray-400'}`}>
                    {c.type_desc === 'Selected' ? 'call-up' : 'recalled'}
                  </span>
                  {c.inventory_match && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-600 text-white font-bold">
                      YOU OWN {c.matched_card_count}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {data.articles.length > 0 && (
            <div className="space-y-1">
              {data.articles.map((a, i) => (
                <a key={i} href={a.link} target="_blank" rel="noopener noreferrer"
                   className="block text-sm text-gray-300 hover:text-emerald-400 truncate">
                  {a.title}
                  <span className="text-gray-500 text-xs"> — {a.source}{a.age_days === 0 ? ' · today' : a.age_days ? ` · ${a.age_days}d` : ''}</span>
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
