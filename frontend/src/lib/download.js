// Shared plumbing for the three authenticated file downloads (database
// backup, inventory CSV, sold-cards CSV). All three fetch as blobs rather
// than linking, because a plain <a href> cannot carry the Bearer header —
// which means they also have to re-implement, by hand, the two things a real
// link gets for free: a filename and a readable error.

/**
 * Filename from a `Content-Disposition` header, or `fallback`.
 *
 * The server already names these files, and its name is the better one: the
 * backup's carries the time, not just the date, so two snapshots taken on the
 * same day don't collide in the downloads folder — and it is stamped from the
 * server's own clock rather than the browser's, so it cannot disagree with
 * what is inside the file.
 *
 * Handles RFC 5987 `filename*=` (preferred when present, being the
 * encoding-aware form) and plain quoted or bare `filename=`.
 */
export function filenameFromContentDisposition(header, fallback) {
  const value = typeof header === 'string' ? header : ''

  const extended = /filename\*\s*=\s*([^;]+)/i.exec(value)
  if (extended) {
    const clean = sanitize(safeDecode(extValue(extended[1].trim())))
    if (clean) return clean
  }

  const plain = /filename\s*=\s*(?:"([^"]*)"|([^;]*))/i.exec(value)
  if (plain) {
    const clean = sanitize((plain[1] ?? plain[2] ?? '').trim())
    if (clean) return clean
  }

  return fallback
}

/**
 * The value half of an RFC 5987 ext-value.
 *
 * The grammar is `charset "'" [ language ] "'" value-chars`, and the language
 * component is optional but may be present: `UTF-8'en'caf%C3%A9.db` is a legal
 * header. Matching the literal prefix `UTF-8''` therefore misses the form that
 * carries a language and leaves `UTF-8'en'` sitting in the filename. Split on
 * the two apostrophes instead and take what follows.
 *
 * The charset is read but not honoured: everything in practice sends UTF-8,
 * which is what `decodeURIComponent` assumes. A header claiming ISO-8859-1
 * with high bytes would fail to decode and fall back to the raw text rather
 * than producing mojibake silently.
 */
function extValue(raw) {
  const unquoted = raw.replace(/^"(.*)"$/, '$1')
  const parts = unquoted.split("'")
  // Fewer than three parts means no ext-value structure at all — treat the
  // whole thing as the value rather than dropping it.
  return parts.length >= 3 ? parts.slice(2).join("'") : unquoted
}

function safeDecode(raw) {
  try {
    return decodeURIComponent(raw)
  } catch {
    // A stray % in the header is not worth failing a download over.
    return raw
  }
}

// Characters no filesystem should be handed. Spelled out as a set, never as
// a range starting at space — a space-to-'<' range also swallows every digit,
// and these filenames are mostly digits. Path separators are already gone by
// the time this runs (sanitize takes a basename first).
const UNSAFE_IN_FILENAME = /[<>:"|?*]/g

function sanitize(name) {
  // basename first — the value is header-supplied and is about to be used as
  // a filename. A leading dot would make it a hidden file, and no name this
  // app sends starts with one.
  const base = String(name).split(/[/\\]/).pop() || ''
  return base.replace(UNSAFE_IN_FILENAME, '').replace(/^\.+/, '').trim()
}

/**
 * Hand a blob to the browser as a download.
 *
 * The object URL is revoked on a later task, not in the same tick as the
 * click: `click()` only *schedules* the download, and the browser fetches the
 * blob: URL after the current task ends — so revoking immediately afterwards
 * raced that fetch, and on Firefox in particular the download silently did
 * nothing at all. The anchor is attached to the document for the same class
 * of reason: an in-document anchor is the idiom browsers have always honoured
 * for a synthetic click.
 */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  // Long enough that the browser has certainly started reading the URL, short
  // enough that the blob isn't pinned for the life of the page.
  setTimeout(() => {
    a.remove()
    URL.revokeObjectURL(url)
  }, 30_000)
}

/**
 * Re-read a blob error body as JSON so the API's `detail` survives.
 *
 * With `responseType: 'blob'`, axios hands back the *error* body as a Blob
 * too, so `err.response.data.detail` is undefined and `formatApiError` falls
 * through to its generic fallback — the server's actual message (that the
 * volume is out of space for a backup snapshot, say) never reaches the
 * screen. Returns the same error object, mutated, so callers can rethrow it.
 */
export async function readBlobError(err) {
  const data = err?.response?.data
  if (data && typeof data.text === 'function') {
    try {
      err.response.data = JSON.parse(await data.text())
    } catch {
      // Not JSON (a proxy's HTML error page, say) — leave it alone and let
      // the caller's fallback message stand.
    }
  }
  return err
}
