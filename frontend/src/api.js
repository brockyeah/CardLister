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

// Same-origin in production; Vite dev proxy handles /api and /uploads in dev.
const api = axios.create({ baseURL: '/' })

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
export const scanCard = (file, preset = 'balance', backFile = null) => {
  const fd = new FormData()
  fd.append('image', file)
  fd.append('preset', preset)
  if (backFile) fd.append('back', backFile)
  return api
    .post('/api/scan', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
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
