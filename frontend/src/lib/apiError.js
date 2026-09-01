// FastAPI puts a *string* in `detail` for normal errors but an *array of
// error objects* for 422 validation failures. Rendering that array directly
// crashes React ("Objects are not valid as a React child") and white-screens
// the page mid-save — always normalize to a string before it reaches JSX.
export function formatApiError(err, fallback = 'Request failed.') {
  const detail = err?.response?.data?.detail
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => d?.msg).filter(Boolean)
    return msgs.length ? msgs.join('; ') : fallback
  }
  if (typeof detail === 'string' && detail) return detail
  // A client-side timeout carries no response, so it used to reach the caller
  // as the generic fallback ("Scan failed. Try again.") — which is wrong in the
  // one way that costs money: the request was abandoned *here*, and the server
  // may well have finished the work and billed it. Saying so is the difference
  // between the user retrying blind and the user checking Analytics first.
  if (err?.code === 'ECONNABORTED') {
    return 'The request took too long and was given up on. The server may have finished it anyway — check before retrying.'
  }
  return fallback
}

/**
 * Whether this error is the request being deliberately cancelled by us rather
 * than failing.
 *
 * Aborting is an outcome the user asked for (clearing the batch queue drops
 * the scan in flight along with it), so it must not be rendered as an error —
 * there is nothing for them to do about it and nothing went wrong.
 */
export function isCanceled(err) {
  return err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError' || err?.name === 'AbortError'
}
