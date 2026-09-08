import axios from 'axios'
import { filenameFromContentDisposition, readBlobError, saveBlob } from './lib/download.js'

const TOKEN_KEY = 'cardlister_token'
const USERNAME_KEY = 'cardlister_username'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t)
export const getUsername = () => localStorage.getItem(USERNAME_KEY)
export const setUsername = (u) => localStorage.setItem(USERNAME_KEY, u)
export const clearToken = () => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USERNAME_KEY)
}

// A hung request with no ceiling leaves its consumer stuck in whichever spinner
// launched it — a hung `/api/pricing` leaves the Comps modal spinning with no
// error, a hung save leaves the Save button disabled with the card unsaved, a
// hung listCards shows an empty inventory that looks like an empty inventory.
// Axios' own default is no timeout at all, which is why every one of those
// modes is silent. 30s is generous for everything routed here: `/api/pricing`
// is capped server-side by `PRICING_DEADLINE_SECONDS` (~20s), an ordinary
// `/api/cards` write is milliseconds, and the CSV export/import run against a
// bounded row limit. `scanCard` legitimately runs longer and sets its own
// timeout per-request, which overrides this default rather than being capped
// by it — axios uses the request-level value when both are provided. The
// existing `formatApiError` covers the toast text for the ECONNABORTED that
// this produces.
const REQUEST_TIMEOUT_MS = 30_000

// Same-origin in production; Vite dev proxy handles /api and /uploads in dev.
const api = axios.create({ baseURL: '/', timeout: REQUEST_TIMEOUT_MS })

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (resp) => resp,
  (err) => {
    if (err.response?.status === 401) {
      clearToken()
      // Hard reload so any in-memory state is dropped — simplest possible logout.
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)

// --- Auth ---
export const login = (username, password) =>
  api.post('/api/auth/login', { username, password }).then((r) => r.data)

// --- Analytics / cost split ---
// params: { range: 'today'|'7d'|'30d'|'month'|'all', user?, model? }
export const getAnalytics = (params = {}) =>
  api.get('/api/analytics', { params }).then((r) => r.data)

export const reassignUser = (from_user, to_user) =>
  api.post('/api/analytics/users/reassign', { from_user, to_user }).then((r) => r.data)
export const deleteUserData = (username) =>
  api.delete(`/api/analytics/users/${encodeURIComponent(username)}/data`).then((r) => r.data)
export const getConfiguredUsers = () =>
  api.get('/api/analytics/users/configured').then((r) => r.data)
// Blob download — a plain <a href> can't carry the Bearer token, so all three
// of these fetch the bytes and synthesize the download. `saveBlob` owns the
// object-URL lifetime (revoking it in the same tick as the click raced the
// browser's own fetch of it) and `readBlobError` recovers the API's `detail`
// from a body axios hands back as a Blob.
const downloadFile = (url, fallbackName, config = {}) =>
  api
    .get(url, { ...config, responseType: 'blob' })
    .then((r) => {
      saveBlob(r.data, filenameFromContentDisposition(
        r.headers?.['content-disposition'], fallbackName,
      ))
    })
    .catch((err) => readBlobError(err).then((e) => Promise.reject(e)))

export const downloadBackup = () =>
  // The fallback name is only reached if the server sends no
  // Content-Disposition; its own name carries the snapshot time, from its own
  // clock, so two backups on one day don't collide.
  downloadFile('/api/analytics/backup.db', 'cardlister-backup.db')

export const getUploadOrphans = () =>
  api.get('/api/analytics/uploads/orphans').then((r) => r.data)
export const cleanupUploadOrphans = () =>
  api.post('/api/analytics/uploads/cleanup').then((r) => r.data)
export const getStorageUsage = () =>
  api.get('/api/analytics/storage').then((r) => r.data)
export const resyncSheet = () =>
  api.post('/api/sheets/resync').then((r) => r.data)

// --- News / call-up ticker ---
export const getNews = () => api.get('/api/news').then((r) => r.data)

// --- Scan ---
// A scan legitimately takes 15-30s, so it needs a far longer ceiling than the
// axios instance's own default (see above). Passed per-request rather than
// hoisted to a second client: axios uses the request-level `timeout` when
// both are provided, so this override cleanly beats the 30s default without
// leaving other scan-adjacent calls (upload preflight, error rendering) on a
// path with no ceiling.
//
// The number is chosen to sit above the server's own worst case rather than
// picked for feel: the subscription path is hard-capped at
// SUBSCRIPTION_SCAN_TIMEOUT (150s by default) and the API path answers in
// 15-30s. Five minutes clears both with room for a slow upload on a phone
// connection, so this can only ever fire on a scan that was never coming back.
// Erring long is the right direction — aborting here does not stop the server,
// which has already spent the tokens.
export const SCAN_TIMEOUT_MS = 300_000

export const scanCard = (file, preset = 'balance', backFile = null, { signal } = {}) => {
  const fd = new FormData()
  fd.append('image', file)
  fd.append('preset', preset)
  if (backFile) fd.append('back', backFile)
  return api
    .post('/api/scan', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: SCAN_TIMEOUT_MS,
      signal,
    })
    .then((r) => r.data)
}

// --- Pricing ---
export const getPricing = (payload) =>
  api.post('/api/pricing', payload).then((r) => r.data)

// --- Cards ---
export const listCards = (params = {}) =>
  api.get('/api/cards', { params }).then((r) => r.data)

export const createCard = (payload) =>
  api.post('/api/cards', payload).then((r) => r.data)

export const checkDuplicate = (payload) =>
  api.post('/api/cards/check-duplicate', payload).then((r) => r.data)

export const downloadInventoryCsv = () =>
  downloadFile('/api/cards/export.csv', 'cardlister-inventory.csv')

export const getSoldYears = () =>
  api.get('/api/cards/sold-years').then((r) => r.data)

// `year` omitted exports every recorded sale.
export const downloadSoldCsv = (year) =>
  downloadFile(
    '/api/cards/export-sold.csv',
    `cardlister-sold-${year || 'all'}.csv`,
    { params: year ? { year } : {} },
  )

export const importInventoryCsv = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api
    .post('/api/cards/import.csv', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => r.data)
}

export const updateCard = (id, payload) =>
  api.patch(`/api/cards/${id}`, payload).then((r) => r.data)

export const deleteCard = (id) =>
  api.delete(`/api/cards/${id}`).then((r) => r.data)

export const markSold = (id, payload) =>
  api.post(`/api/cards/${id}/mark-sold`, payload).then((r) => r.data)

export const unmarkSold = (id) =>
  api.post(`/api/cards/${id}/unmark-sold`).then((r) => r.data)

export const attachEbayListing = (id, payload) =>
  api.post(`/api/cards/${id}/ebay-id`, payload).then((r) => r.data)

// --- eBay listing text ---
export const getEbayListingText = (id) =>
  api.get(`/api/ebay/${id}/listing-text`).then((r) => r.data)
