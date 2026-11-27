import axios from 'axios'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('hrms_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      localStorage.removeItem('hrms_token')
      if (window.location.pathname !== '/login') window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export const errorMessage = (error) => {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === 'string' ? item : item?.msg || JSON.stringify(item)))
      .join('; ')
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return detail || error?.message || 'Something went wrong'
}

export default api
