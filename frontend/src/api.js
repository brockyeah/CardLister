import axios from 'axios'

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

export const updateCard = (id, payload) =>
  api.patch(`/api/cards/${id}`, payload).then((r) => r.data)

export const deleteCard = (id) =>
  api.delete(`/api/cards/${id}`).then((r) => r.data)

export const markSold = (id, payload) =>
  api.post(`/api/cards/${id}/mark-sold`, payload).then((r) => r.data)

export const attachEbayListing = (id, payload) =>
  api.post(`/api/cards/${id}/ebay-id`, payload).then((r) => r.data)

// --- eBay listing text ---
export const getEbayListingText = (id) =>
  api.get(`/api/ebay/${id}/listing-text`).then((r) => r.data)

export default api
