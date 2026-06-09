const API_BASE = import.meta.env.VITE_API_BASE || '/api'

async function getResponseError(response) {
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    const payload = await response.json()
    return payload.detail || payload.message || `Request failed: ${response.status}`
  }
  return (await response.text()) || `Request failed: ${response.status}`
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })

  if (!response.ok) {
    throw new Error(await getResponseError(response))
  }

  return response.json()
}

export { API_BASE, getResponseError, request }
