import { useRef, useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import CardForm from '../components/CardForm.jsx'
import NewsSection from '../components/NewsSection.jsx'
import { scanCard, getPricing, createCard, updateCard, checkDuplicate, getEbayListingText } from '../api'

const EMPTY_FORM = {
  player_name: '',
  year: null,
  brand: '',
  set_name: '',
  card_number: '',
  team: '',
  is_rookie: false,
  is_first_bowman: false,
  is_autograph: false,
  is_patch: false,
  is_refractor: false,
  parallel_color: null,
  serial_number: null,
  condition: 'NM',
  quantity: 1,
  suggested_price: null,
  listed_price: null,
  image_path: '',
  back_image_path: '',
  notes: '',
}

const EBAY_SELL_URL = 'https://www.ebay.com/sl/sell'

// Keep keys in sync with PRESETS in backend/services/claude_vision.py.
const SCAN_MODES = [
  { key: 'cost', label: 'Cost', desc: 'Sonnet 4.6 · low thinking · smaller image — cheapest' },
  { key: 'balance', label: 'Balanced', desc: 'Opus 4.7 · medium thinking' },
  { key: 'accuracy', label: 'Accuracy', desc: 'Opus 4.7 · high thinking · hi-res image — most thorough' },
]
const SCAN_MODE_KEY = 'cardlister_scan_mode'

export default function Scanner() {
  const fileInputRef = useRef(null)
  const dropRef = useRef(null)

  // Three stages: nothing → file staged (preview shown, scan not started) → scanned (form visible)
  const [stagedFile, setStagedFile] = useState(null)
  const [stagedPreview, setStagedPreview] = useState('')   // local object URL for preview
  const [stagedIsPdf, setStagedIsPdf] = useState(false)

  const [stagedBack, setStagedBack] = useState(null)
  const [stagedBackPreview, setStagedBackPreview] = useState('')
  const backInputRef = useRef(null)

  const [scanning, setScanning] = useState(false)
  const [pricingLoading, setPricingLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Scan mode (model + thinking preset), remembered across sessions.
  const [mode, setMode] = useState(() => localStorage.getItem(SCAN_MODE_KEY) || 'balance')
  const chooseMode = (key) => {
    setMode(key)
    localStorage.setItem(SCAN_MODE_KEY, key)
  }

  // Batch mode (2+ files staged at once). Scans run strictly one at a time;
  // pricing is fetched only when the user opens a card for review.
  const [queue, setQueue] = useState([])            // [{key, file, status, result, error}]
  const [activeKey, setActiveKey] = useState(null)  // queue item currently in the form
  const processingRef = useRef(false)

  const [form, setForm] = useState(EMPTY_FORM)
  const [imagePath, setImagePath] = useState('')          // server path once scanned
  const [mock, setMock] = useState(false)
  const [scanId, setScanId] = useState(null)

  const [comps, setComps] = useState([])
  const [pricingNote, setPricingNote] = useState('')
  const [pricingSource, setPricingSource] = useState('')

  const [toast, setToast] = useState(null)
  const [error, setError] = useState('')

  // Duplicate prompt: { data, existing } while asking the user whether to
  // bump the existing card's count instead of saving a new row.
  const [dupPrompt, setDupPrompt] = useState(null)
  const cameraInputRef = useRef(null)

  // --- Staging (no upload yet — just shows what's about to be scanned) ---
  const stageFile = (file) => {
    if (!file) return
    setError('')
    if (stagedPreview) URL.revokeObjectURL(stagedPreview)
    setStagedFile(file)
    setStagedIsPdf(file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'))
    setStagedPreview(URL.createObjectURL(file))
  }

  const clearStaged = () => {
    if (stagedPreview) URL.revokeObjectURL(stagedPreview)
    setStagedFile(null)
    setStagedPreview('')
    setStagedIsPdf(false)
    if (stagedBackPreview) URL.revokeObjectURL(stagedBackPreview)
    setStagedBack(null)
    setStagedBackPreview('')
  }

  const stageFiles = (fileList) => {
    const files = Array.from(fileList || [])
    if (files.length === 0) return
    if (files.length === 1) {
      stageFile(files[0])
      return
    }
    // Batch mode: front images only, no back slot.
    clearStaged()
    setActiveKey(null)
    setQueue(files.map((file, i) => ({
      key: `${Date.now()}-${i}`, file, status: 'queued', result: null, error: null,
    })))
  }

  const fetchPricing = async (next) => {
    setPricingLoading(true)
    try {
      const pricing = await getPricing({
        player_name: next.player_name,
        year: next.year,
        brand: next.brand,
        set_name: next.set_name,
        card_number: next.card_number,
      })
      setComps(pricing.comps || [])
      setPricingNote(pricing.note || '')
      setPricingSource(pricing.source || '')
      if (pricing.suggested_price) {
        setForm((prev) => ({ ...prev, suggested_price: pricing.suggested_price }))
      }
    } catch {
      setPricingNote('Pricing lookup failed — set price manually.')
    } finally {
      setPricingLoading(false)
    }
  }

  // --- Actual scan — runs only when user clicks the Scan button ---
  const runScan = async () => {
    if (!stagedFile) return
    setError('')
    setScanning(true)
    setComps([])
    setPricingNote('')
    setPricingSource('')
    try {
      const result = await scanCard(stagedFile, mode, stagedBack)
      setImagePath(result.image_path)
      setMock(!!result.mock)
      setScanId(result.scan_id ?? null)
      // A real extraction was attempted but failed (distinct from mock mode) —
      // surface it instead of the misleading "set ANTHROPIC_API_KEY" banner.
      if (result.error) setError(result.error)
      const next = { ...EMPTY_FORM, ...result.extracted, image_path: result.image_path, back_image_path: result.back_image_path || '' }
      setForm(next)
      clearStaged()

      await fetchPricing(next)
    } catch (e) {
      setError(e.response?.data?.detail || 'Scan failed. Try again.')
    } finally {
      setScanning(false)
    }
  }

  // Sequential processor (one scan in flight, ever):
  useEffect(() => {
    const next = queue.find((q) => q.status === 'queued')
    if (!next || processingRef.current) return
    processingRef.current = true
    const mark = (key, patch) =>
      setQueue((prev) => prev.map((q) => (q.key === key ? { ...q, ...patch } : q)))
    mark(next.key, { status: 'scanning' })
    scanCard(next.file, mode)
      .then((result) => mark(next.key, { status: 'ready', result }))
      .catch((e) => mark(next.key, { status: 'error', error: e.response?.data?.detail || 'Scan failed' }))
      .finally(() => { processingRef.current = false })
  }, [queue, mode])

  // Review a queue item (loads it into the existing form + fetches pricing):
  const reviewQueueItem = async (item) => {
    const result = item.result
    if (!result) return
    setError(result.error || '')
    setImagePath(result.image_path)
    setMock(!!result.mock)
    setScanId(result.scan_id ?? null)
    setComps([])
    setPricingNote('')
    setPricingSource('')
    const next = { ...EMPTY_FORM, ...result.extracted, image_path: result.image_path, back_image_path: result.back_image_path || '' }
    setForm(next)
    setActiveKey(item.key)
    await fetchPricing(next)
  }

  // Reset the form + advance the batch queue, shared by every save outcome.
  const resetAfterSave = () => {
    setForm(EMPTY_FORM)
    setImagePath('')
    setComps([])
    setMock(false)
    setScanId(null)
    setPricingNote('')
    setPricingSource('')

    if (activeKey) {
      // Compute from the render snapshot — reading state back out of a
      // setQueue updater is deferred by React and never runs in time here.
      const nextReady = queue.find((q) => q.key !== activeKey && q.status === 'ready') || null
      setQueue((prev) => prev.map((q) => (q.key === activeKey ? { ...q, status: 'saved' } : q)))
      setActiveKey(null)
      if (nextReady) setTimeout(() => reviewQueueItem(nextReady), 0)
    }
  }

  // --- Save + copy listing to clipboard + open eBay ---
  const doSave = async (data) => {
    setSubmitting(true)
    setError('')
    try {
      const created = await createCard({ ...data, image_path: imagePath, scan_id: scanId })

      // eBay's pre-fill URL params no longer reliably populate the sell form.
      // Workaround: copy a complete title+price+description block to the
      // clipboard, then open eBay's sell page so user can paste.
      let clipboardOk = false
      try {
        const text = await getEbayListingText(created.id)
        await navigator.clipboard.writeText(text.clipboard_text)
        clipboardOk = true
      } catch {
        clipboardOk = false
      }
      window.open(EBAY_SELL_URL, '_blank', 'noopener')

      resetAfterSave()

      setToast({
        id: created.id,
        message: clipboardOk
          ? 'Card saved. Listing text copied to clipboard — paste it into eBay.'
          : 'Card saved. (Could not access clipboard — open the card in Inventory to copy manually.)',
      })
      setTimeout(() => setToast(null), 8000)
    } catch (e) {
      setError(e.response?.data?.detail || 'Save failed.')
    } finally {
      setSubmitting(false)
    }
  }

  // Duplicate gate: ask before creating a second row for a card already owned.
  const handleSubmit = async (data) => {
    try {
      const { duplicate } = await checkDuplicate(data)
      if (duplicate) {
        setDupPrompt({ data, existing: duplicate })
        return
      }
    } catch {
      // Never block a save on the dup check — fall through and save normally.
    }
    await doSave(data)
  }

  const increaseCount = async () => {
    const { existing } = dupPrompt
    setDupPrompt(null)
    setSubmitting(true)
    setError('')
    try {
      const updated = await updateCard(existing.id, { quantity: (existing.quantity || 1) + 1 })
      resetAfterSave()
      setToast({
        id: updated.id,
        message: `Card count increased — you now have ${updated.quantity} copies of ${updated.player_name}.`,
      })
      setTimeout(() => setToast(null), 8000)
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to update card count.')
    } finally {
      setSubmitting(false)
    }
  }

  // --- Drag and drop ---
  const onDrop = (e) => {
    e.preventDefault()
    dropRef.current?.classList.remove('ring-emerald-500')
    stageFiles(e.dataTransfer.files)
  }

  // What stage of the workflow are we in?
  const isStaged = !!stagedFile && !imagePath
  const isScanned = !!imagePath

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-1">Scan a Card</h1>
        <p className="text-gray-400 text-sm">
          Upload a photo or PDF. Click Scan. Review the details. Save to copy the listing text and open eBay.
        </p>
      </div>

      {/* Scan mode: model + thinking-effort preset, applied to the next scan. */}
      <div className="card-panel">
        <div className="label mb-2">Scan mode</div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {SCAN_MODES.map((m) => {
            const active = mode === m.key
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => chooseMode(m.key)}
                className={`text-left rounded-lg px-3 py-2 border transition ${
                  active
                    ? 'border-emerald-500 bg-emerald-600/15'
                    : 'border-ink-600 bg-ink-800 hover:border-ink-500'
                }`}
              >
                <div className={`font-semibold ${active ? 'text-emerald-300' : 'text-gray-200'}`}>
                  {m.label}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">{m.desc}</div>
              </button>
            )
          })}
        </div>
      </div>

      {toast && (
        <div className="bg-emerald-900/40 border border-emerald-600 text-emerald-100 rounded-lg px-4 py-3 flex items-center justify-between gap-3">
          <span>{toast.message}</span>
          <Link to="/inventory" className="underline text-emerald-300 font-semibold whitespace-nowrap">View Inventory →</Link>
        </div>
      )}

      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-200 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {queue.length > 0 && (
        <div className="card-panel">
          <div className="flex items-center justify-between mb-3">
            <div className="font-bold">Batch queue ({queue.filter((q) => q.status === 'saved').length}/{queue.length} saved)</div>
            <button
              type="button"
              className="text-xs text-gray-400 underline"
              onClick={() => { setQueue([]); setActiveKey(null) }}
            >
              Clear queue
            </button>
          </div>
          <div className="space-y-1.5">
            {queue.map((q) => (
              <div key={q.key} className="flex items-center gap-3 text-sm">
                <span className="flex-1 truncate text-gray-300">{q.file.name}</span>
                {q.status === 'queued' && <span className="text-gray-500 text-xs">waiting…</span>}
                {q.status === 'scanning' && <span className="text-yellow-400 text-xs">scanning…</span>}
                {q.status === 'error' && <span className="text-red-400 text-xs">{q.error}</span>}
                {q.status === 'saved' && <span className="text-emerald-500 text-xs">saved ✓</span>}
                {q.status === 'ready' && (
                  <button
                    type="button"
                    onClick={() => reviewQueueItem(q)}
                    className={`text-xs rounded px-2 py-1 ${activeKey === q.key ? 'bg-emerald-600 text-white' : 'bg-ink-700 text-gray-200 hover:bg-ink-600'}`}
                  >
                    {activeKey === q.key ? 'Reviewing' : 'Review'}
                  </button>
                )}
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-3">Cards scan one at a time. Back-of-card images aren't supported in batch mode — scan those individually.</p>
        </div>
      )}

      {/* STAGE 1: nothing uploaded yet — show the drop zone */}
      {!isStaged && !isScanned && queue.length === 0 && (
        <div
          ref={dropRef}
          onDragOver={(e) => {
            e.preventDefault()
            dropRef.current?.classList.add('ring-emerald-500')
          }}
          onDragLeave={() => dropRef.current?.classList.remove('ring-emerald-500')}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
          className="card-panel border-2 border-dashed border-ink-600 ring-2 ring-transparent cursor-pointer text-center py-16 hover:border-emerald-500 transition"
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,application/pdf"
            multiple
            className="hidden"
            onChange={(e) => stageFiles(e.target.files)}
          />
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => stageFiles(e.target.files)}
          />
          <div className="text-5xl mb-3">📸</div>
          <div className="text-xl font-bold mb-1">Tap to choose a file or drop one here</div>
          <div className="text-gray-400 text-sm">JPG, PNG, WEBP, or PDF — select multiple files to batch scan</div>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              cameraInputRef.current?.click()
            }}
            className="btn-secondary mt-5"
          >
            📷 Take a Photo
          </button>
        </div>
      )}

      {/* STAGE 2: file staged — show preview + Scan button (user-initiated) */}
      {isStaged && (
        <div className="card-panel">
          <div className="flex flex-col md:flex-row gap-5 items-start">
            <div className="w-full md:w-64 flex-shrink-0">
              {stagedIsPdf ? (
                <div className="bg-ink-900 border border-ink-700 rounded-lg flex flex-col items-center justify-center py-12 text-gray-400">
                  <div className="text-5xl mb-2">📄</div>
                  <div className="text-sm font-mono break-all px-2 text-center">{stagedFile.name}</div>
                  <div className="text-xs mt-2">PDF document</div>
                </div>
              ) : (
                <img src={stagedPreview} alt="Staged" className="w-full rounded-lg" />
              )}
            </div>
            <div className="flex-1 w-full space-y-3">
              <div className="text-lg font-bold">Ready to scan</div>
              <div className="text-sm text-gray-400">
                File: <span className="font-mono text-gray-200">{stagedFile.name}</span>
                <br />
                Size: {(stagedFile.size / 1024).toFixed(0)} KB
              </div>
              <button
                onClick={runScan}
                disabled={scanning}
                className="btn-primary w-full text-lg"
              >
                {scanning ? 'Scanning… this can take 15-30s' : 'Scan This Card'}
              </button>
              <button
                onClick={() => {
                  clearStaged()
                  fileInputRef.current?.click()
                }}
                disabled={scanning}
                className="btn-secondary w-full"
              >
                Choose a Different File
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,application/pdf"
                multiple
                className="hidden"
                onChange={(e) => stageFiles(e.target.files)}
              />
              <input
                ref={backInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (!f) return
                  if (stagedBackPreview) URL.revokeObjectURL(stagedBackPreview)
                  setStagedBack(f)
                  setStagedBackPreview(URL.createObjectURL(f))
                }}
              />
              {stagedBack ? (
                <div className="flex items-center gap-3 text-sm text-gray-300">
                  <img src={stagedBackPreview} alt="Back" className="w-12 h-16 object-cover rounded" />
                  <span className="flex-1 truncate">Back: {stagedBack.name}</span>
                  <button type="button" className="text-red-400 underline text-xs"
                          onClick={() => { URL.revokeObjectURL(stagedBackPreview); setStagedBack(null); setStagedBackPreview('') }}>
                    Remove
                  </button>
                </div>
              ) : (
                <button type="button" onClick={() => backInputRef.current?.click()} disabled={scanning}
                        className="btn-secondary w-full">
                  + Add Back of Card (optional, improves accuracy)
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* STAGE 3: scanned — show the editable form */}
      {isScanned && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1">
            <div className="card-panel">
              {imagePath.toLowerCase().endsWith('.pdf') ? (
                <div className="bg-ink-900 border border-ink-700 rounded-lg flex flex-col items-center justify-center py-12 mb-3 text-gray-400">
                  <div className="text-5xl mb-2">📄</div>
                  <a href={imagePath} target="_blank" rel="noreferrer" className="underline text-emerald-400 text-sm">
                    Open PDF
                  </a>
                </div>
              ) : (
                <img src={imagePath} alt="Card" className="w-full rounded-lg mb-3" />
              )}
              {form.back_image_path && (
                <img src={form.back_image_path} alt="Card back" className="w-full rounded-lg mb-3" />
              )}
              <button
                onClick={() => {
                  setForm(EMPTY_FORM)
                  setImagePath('')
                  setComps([])
                  setScanId(null)
                  setActiveKey(null)
                  setPricingSource('')
                }}
                className="btn-secondary w-full"
              >
                Discard & Start Over
              </button>
              {pricingLoading && (
                <div className="text-xs text-gray-400 mt-3 text-center">Looking up comps…</div>
              )}
              {pricingSource && pricingSource !== 'mock' && (
                <div className="text-xs text-emerald-400 mt-3 text-center">
                  Prices from: {pricingSource === 'ebay_sold' ? 'eBay sold listings' : pricingSource}
                </div>
              )}
              {pricingNote && (
                <div className="text-xs text-yellow-400 mt-3 text-center">{pricingNote}</div>
              )}
            </div>
          </div>
          <div className="lg:col-span-2">
            <CardForm
              initial={form}
              onChange={setForm}
              onSubmit={handleSubmit}
              submitting={submitting}
              comps={comps}
              suggestedPrice={form.suggested_price}
              mock={mock}
            />
          </div>
        </div>
      )}

      {dupPrompt && (() => {
        const c = dupPrompt.existing
        const label = [c.year, c.brand, c.set_name, c.player_name, c.card_number && `#${c.card_number}`]
          .filter(Boolean).join(' ')
        const qty = c.quantity || 1
        return (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-20 px-4">
            <div className="card-panel w-full max-w-md">
              <h2 className="text-xl font-bold mb-2">Looks like you already own this card!</h2>
              <div className="flex items-center gap-3 bg-ink-900 border border-ink-700 rounded-lg px-3 py-2 mb-3">
                {c.image_path ? (
                  <img src={c.image_path} alt="" className="w-10 h-14 object-cover rounded" />
                ) : (
                  <div className="w-10 h-14 bg-ink-700 rounded" />
                )}
                <div className="text-sm">
                  <div className="font-semibold text-gray-100">{label}</div>
                  <div className="text-gray-400">
                    {qty === 1 ? '1 copy' : `${qty} copies`} in inventory
                    {c.listed_price != null && ` · listed at $${Number(c.listed_price).toFixed(2)}`}
                  </div>
                </div>
              </div>
              <p className="text-sm text-gray-400 mb-4">
                Would you like to increase your card count instead of creating a new entry?
              </p>
              <div className="flex gap-2">
                <button type="button" onClick={increaseCount} disabled={submitting} className="btn-primary flex-1">
                  Yes, Increase Count to {qty + 1}
                </button>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => {
                    const { data } = dupPrompt
                    setDupPrompt(null)
                    doSave(data)
                  }}
                  className="btn-secondary flex-1"
                >
                  No, Save as New Card
                </button>
              </div>
              <button
                type="button"
                onClick={() => setDupPrompt(null)}
                className="text-xs text-gray-400 underline mt-3 mx-auto block"
              >
                Cancel — keep editing
              </button>
            </div>
          </div>
        )
      })()}

      <NewsSection />
    </div>
  )
}
