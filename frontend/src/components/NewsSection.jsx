import { useEffect, useState } from 'react'
import { getNews } from '../api'

// Same guard as CardTable's listing links: article links come from external
// RSS feeds, so never render a non-http(s) value as a clickable href.
const isSafeHttpUrl = (url) => /^https?:\/\//i.test(url || '')

const KEY = 'cardlister_news_open'
const SERIF = "font-['Georgia',serif]"

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

  const dateline = new Date().toLocaleDateString('en-US', {
    month: 'long', day: 'numeric', year: 'numeric',
  })

  return (
    <div className="card-panel sm:p-6">
      {/* Masthead */}
      <button onClick={toggle} className="w-full text-left block">
        <div className="border-t border-ink-700" />
        <div className="text-center py-2">
          <span className={`${SERIF} font-bold text-2xl tracking-tight text-emerald-400`}>
            PROSPECT WIRE
          </span>
        </div>
        <div className="border-t-2 border-emerald-600" />
        <div className="border-t border-ink-600 mt-[2px]" />
        <div className="flex items-center justify-between text-xs text-gray-400 mt-2">
          <span>
            Call-Ups &amp; Prospect News<span className="mx-1.5 text-emerald-600">·</span>{dateline}
          </span>
          <span className="text-sm">{open ? '▾' : '▸'}</span>
        </div>
      </button>

      {/* Body */}
      {open && (
        <div className="mt-5 grid grid-cols-1 md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] gap-6">
          {/* Left — transactions */}
          <div className="md:pr-6 md:border-r md:border-ink-700">
            {data.callups.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 pb-1 border-b border-emerald-600/40 mb-3">
                  Transactions
                </div>
                <div className="divide-y divide-ink-700">
                  {data.callups.map((c, i) => {
                    const isCallup = c.type_desc === 'Selected'
                    return (
                      <div key={i} className={`py-2 text-[13px] ${SERIF} leading-snug`}>
                        <div className="flex items-baseline gap-1.5 flex-wrap">
                          <span className="text-gray-500 tabular-nums text-xs">{c.date}</span>
                          <span className={`font-bold ${c.inventory_match ? 'text-emerald-300' : 'text-gray-100'}`}>
                            {c.player_name}
                          </span>
                          <span className="text-gray-400">— {c.to_team}</span>
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          {isCallup ? (
                            <span className="text-[10px] font-sans uppercase tracking-wide text-emerald-300 border border-emerald-700/60 rounded-sm px-1 py-0.5">
                              Call-Up
                            </span>
                          ) : (
                            <span className="text-[10px] font-sans text-gray-400 bg-ink-700 rounded-sm px-1 py-0.5">recalled</span>
                          )}
                          {c.inventory_match && (
                            <span className="text-[10px] font-sans font-bold uppercase tracking-wide bg-emerald-600 text-white rounded-sm px-1.5 py-0.5">
                              You Own {c.matched_card_count}
                            </span>
                          )}
                          {c.first_bowman_count > 0 && (
                            <span className="text-[10px] font-sans font-bold uppercase tracking-wide bg-amber-500 text-ink-900 rounded-sm px-1.5 py-0.5">
                              1st Bowman ×{c.first_bowman_count}
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Right — headlines */}
          <div>
            {data.articles.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 pb-1 border-b border-emerald-600/40 mb-3">
                  The Headlines
                </div>
                <div className="divide-y divide-ink-700">
                  {data.articles.map((a, i) => (
                    <div key={i} className={i === 0 ? 'pb-3' : 'py-3'}>
                      <div className="text-[10px] font-sans font-semibold uppercase tracking-widest text-emerald-400 mb-1">
                        {a.source}
                      </div>
                      {isSafeHttpUrl(a.link) ? (
                        <a
                          href={a.link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`${SERIF} font-semibold text-base text-gray-100 hover:text-emerald-300 hover:underline`}
                        >
                          {a.title}
                        </a>
                      ) : (
                        <span className={`${SERIF} font-semibold text-base text-gray-100`}>
                          {a.title}
                        </span>
                      )}
                      {a.summary && (
                        <p className="font-sans text-sm text-gray-400 mt-1 line-clamp-2">{a.summary}</p>
                      )}
                      <div className="font-sans text-xs text-gray-500 mt-1">
                        {a.source}
                        {a.age_days === 0 ? ' · today' : a.age_days ? ` · ${a.age_days}d ago` : ''}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
