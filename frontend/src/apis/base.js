const API_BASE = import.meta.env.VITE_API_BASE || '/api'
const AUTH_TOKEN_KEY = 'minibot_auth_token'
let activeAuthToken = sessionStorage.getItem(AUTH_TOKEN_KEY) || localStorage.getItem(AUTH_TOKEN_KEY) || ''

// 认证状态按标签页隔离，避免多个账号在不同标签页登录时互相覆盖令牌。
if (activeAuthToken && !sessionStorage.getItem(AUTH_TOKEN_KEY)) {
  sessionStorage.setItem(AUTH_TOKEN_KEY, activeAuthToken)
}

function getAuthToken() {
  return activeAuthToken
}

function setAuthToken(token) {
  activeAuthToken = token || ''
  if (activeAuthToken) {
    sessionStorage.setItem(AUTH_TOKEN_KEY, activeAuthToken)
  } else {
    sessionStorage.removeItem(AUTH_TOKEN_KEY)
  }
  localStorage.removeItem(AUTH_TOKEN_KEY)
}

function authHeaders(headers = {}) {
  const token = getAuthToken()
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...headers,
  }
}

async function getResponseError(response) {
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    const payload = await response.json()
    return payload.detail || payload.message || `Request failed: ${response.status}`
  }
  return (await response.text()) || `Request failed: ${response.status}`
}

async function request(path, options = {}) {
  const { headers = {}, ...restOptions } = options
  const response = await fetch(`${API_BASE}${path}`, {
    ...restOptions,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(headers),
    },
  })

  if (!response.ok) {
    throw new Error(await getResponseError(response))
  }

  return response.json()
}

export { API_BASE, AUTH_TOKEN_KEY, authHeaders, getAuthToken, getResponseError, request, setAuthToken }
