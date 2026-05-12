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

export function listConversations(userKey) {
  return request(`/conversations?user_key=${encodeURIComponent(userKey)}`)
}

export function updateConversation(conversationId, userKey, payload) {
  return request(`/conversations/${encodeURIComponent(conversationId)}?user_key=${encodeURIComponent(userKey)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteConversation(conversationId, userKey) {
  return request(`/conversations/${encodeURIComponent(conversationId)}?user_key=${encodeURIComponent(userKey)}`, {
    method: 'DELETE',
  })
}

export function listConversationMessages(conversationId, userKey) {
  return request(
    `/conversations/${encodeURIComponent(conversationId)}/messages?user_key=${encodeURIComponent(userKey)}`,
  )
}

export function sendChat(message, userKey, conversationId = null) {
  return request('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, user_key: userKey, conversation_id: conversationId }),
  })
}
