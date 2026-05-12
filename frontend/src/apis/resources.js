import { request } from './base'

export function listResources(kind) {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : ''
  return request(`/resources${query}`)
}

export function getSelection(userKey) {
  return request(`/selections/${encodeURIComponent(userKey)}`)
}

export function saveSelection(userKey, selection) {
  return request(`/selections/${encodeURIComponent(userKey)}`, {
    method: 'PUT',
    body: JSON.stringify(selection),
  })
}

export function sendChat(message, userKey) {
  return request('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, user_key: userKey }),
  })
}
