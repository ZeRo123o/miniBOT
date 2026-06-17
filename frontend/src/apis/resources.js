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

export function getSelection(userId) {
  return request(`/selections/${encodeURIComponent(userId)}`)
}

export function saveSelection(userId, selection) {
  return request(`/selections/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    body: JSON.stringify(selection),
  })
}

export function listConversations(userId) {
  return request(`/conversations?user_id=${encodeURIComponent(userId)}`)
}

export function updateConversation(conversationId, userId, payload) {
  return request(`/conversations/${encodeURIComponent(conversationId)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteConversation(conversationId, userId) {
  return request(`/conversations/${encodeURIComponent(conversationId)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })
}

export function listConversationMessages(conversationId, userId) {
  return request(
    `/conversations/${encodeURIComponent(conversationId)}/messages?user_id=${encodeURIComponent(userId)}`,
  )
}

export function listKnowledgeBases(userId) {
  return request(`/knowledge-bases?user_id=${encodeURIComponent(userId)}`)
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

export function deleteKnowledgeBase(knowledgeBaseId, userId) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  )
}

export function listKnowledgeDocuments(knowledgeBaseId, userId) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents?user_id=${encodeURIComponent(userId)}`,
  )
}

export async function uploadKnowledgeDocument(knowledgeBaseId, userId, file) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(
    `${API_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents?user_id=${encodeURIComponent(userId)}`,
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

export function deleteKnowledgeDocument(documentId, userId) {
  return request(
    `/knowledge-documents/${encodeURIComponent(documentId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  )
}

export async function sendChatStream(message, userId, conversationId = null, handlers = {}, files = []) {
  const hasFiles = Array.isArray(files) && files.length > 0
  const requestOptions = hasFiles
    ? {
        method: 'POST',
        body: buildChatFormData(message, userId, conversationId, files),
      }
    : {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, user_id: userId, conversation_id: conversationId }),
      }

  const response = await fetch(`${API_BASE}/chat/stream`, requestOptions)

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

function buildChatFormData(message, userId, conversationId, files) {
  const formData = new FormData()
  formData.append('message', message)
  formData.append('user_id', userId)
  if (conversationId !== null && conversationId !== undefined) {
    formData.append('conversation_id', String(conversationId))
  }
  for (const file of files) {
    formData.append('files', file)
  }
  return formData
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
