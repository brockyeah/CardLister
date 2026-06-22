import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import CardForm from '../components/CardForm.jsx'
import { scanCard, getPricing, createCard, getEbayListingText } from '../api'

const EMPTY_FORM = {
  player_name: '',
  year: null,
  brand: '',
  set_name: '',
  card_number: '',
  team: '',
  is_rookie: false,
  is_autograph: false,
  is_patch: false,
  is_refractor: false,
  parallel_color: null,
  serial_number: null,
  condition: 'NM',
  suggested_price: null,
  listed_price: null,
  image_path: '',
  notes: '',
}

const EBAY_SELL_URL = 'https://www.ebay.com/sl/sell'

export default function Scanner() {
  const fileInputRef = useRef(null)
  const dropRef = useRef(null)

  // Three stages: nothing → file staged (preview shown, scan not started) → scanned (form visible)
  const [stagedFile, setStagedFile] = useState(null)
  const [stagedPreview, setStagedPreview] = useState('')   // local object URL for preview
  const [stagedIsPdf, setStagedIsPdf] = useState(false)

  const [scanning, setScanning] = useState(false)
  const [pricingLoading, setPricingLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const [form, setForm] = useState(EMPTY_FORM)
  const [imagePath, setImagePath] = useState('')          // server path once scanned
  const [mock, setMock] = useState(false)

  const [comps, setComps] = useState([])
  const [pricingNote, setPricingNote] = useState('')
  const [pricingSource, setPricingSource] = useState('')

  const [toast, setToast] = useState(null)
  const [error, setError] = useState('')

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
      const result = await scanCard(stagedFile)
      setImagePath(result.image_path)
      setMock(!!result.mock)
      // A real extraction was attempted but failed (distinct from mock mode) —
      // surface it instead of the misleading "set ANTHROPIC_API_KEY" banner.
      if (result.error) setError(result.error)
      const next = { ...EMPTY_FORM, ...result.extracted, image_path: result.image_path }
      setForm(next)
      clearStaged()

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
    } catch (e) {
      setError(e.response?.data?.detail || 'Scan failed. Try again.')
    } finally {
      setScanning(false)
    }
  }

  // --- Save + copy listing to clipboard + open eBay ---
  const handleSubmit = async (data) => {
    setSubmitting(true)
    setError('')
    try {
      const created = await createCard({ ...data, image_path: imagePath })

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

      // Reset for next card
      setForm(EMPTY_FORM)
      setImagePath('')
      setComps([])
      setMock(false)
      setPricingNote('')
      setPricingSource('')

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

  // --- Drag and drop ---
  const onDrop = (e) => {
    e.preventDefault()
    dropRef.current?.classList.remove('ring-emerald-500')
    const file = e.dataTransfer.files?.[0]
    if (file) stageFile(file)
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

      {/* STAGE 1: nothing uploaded yet — show the drop zone */}
      {!isStaged && !isScanned && (
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
            className="hidden"
            onChange={(e) => stageFile(e.target.files?.[0])}
          />
          <div className="text-5xl mb-3">📸</div>
          <div className="text-xl font-bold mb-1">Tap to choose a file or drop one here</div>
          <div className="text-gray-400 text-sm">JPG, PNG, WEBP, or PDF</div>
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
                className="hidden"
                onChange={(e) => stageFile(e.target.files?.[0])}
              />
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
              <button
                onClick={() => {
                  setForm(EMPTY_FORM)
                  setImagePath('')
                  setComps([])
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
    </div>
  )
}
