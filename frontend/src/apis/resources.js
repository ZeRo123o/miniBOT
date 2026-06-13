import { API_BASE, getResponseError, request } from './base'

export function listResources(kind) {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : ''
  return request(`/resources${query}`)
}

export function listSkills() {
  return request('/skills')
}

export function upsertResource(resource) {
  return request('/resources', {
    method: 'POST',
    body: JSON.stringify(resource),
  })
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

export function listKnowledgeBases(userKey) {
  return request(`/knowledge-bases?user_key=${encodeURIComponent(userKey)}`)
}

export function listKnowledgeChunkPresets() {
  return request('/knowledge-chunk-presets')
}

export function createKnowledgeBase(payload) {
  return request('/knowledge-bases', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function deleteKnowledgeBase(knowledgeBaseId, userKey) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}?user_key=${encodeURIComponent(userKey)}`,
    { method: 'DELETE' },
  )
}

export function listKnowledgeDocuments(knowledgeBaseId, userKey) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents?user_key=${encodeURIComponent(userKey)}`,
  )
}

export async function uploadKnowledgeDocument(knowledgeBaseId, userKey, file) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(
    `${API_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents?user_key=${encodeURIComponent(userKey)}`,
    {
      method: 'POST',
      body: formData,
    },
  )

  if (!response.ok) {
    throw new Error(await getResponseError(response))
  }

  return response.json()
}

export function deleteKnowledgeDocument(documentId, userKey) {
  return request(
    `/knowledge-documents/${encodeURIComponent(documentId)}?user_key=${encodeURIComponent(userKey)}`,
    { method: 'DELETE' },
  )
}

export async function sendChatStream(message, userKey, conversationId = null, handlers = {}) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_key: userKey, conversation_id: conversationId }),
  })

  if (!response.ok || !response.body) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''

    for (const rawEvent of events) {
      const event = parseStreamEvent(rawEvent)
      if (!event) continue
      if (event.type === 'error') {
        throw new Error(event.detail || 'Stream failed.')
      }
      handlers[event.type]?.(event)
    }
  }

  if (buffer.trim()) {
    const event = parseStreamEvent(buffer)
    if (event) handlers[event.type]?.(event)
  }
}

function parseStreamEvent(rawEvent) {
  const data = rawEvent
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')

  if (!data) return null
  return JSON.parse(data)
}
