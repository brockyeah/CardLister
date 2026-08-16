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
  return fallback
}
