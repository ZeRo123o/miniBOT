import { API_BASE, authHeaders, getResponseError, request } from './base'

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

export function queryKnowledgeBase(knowledgeBaseId, payload) {
  return request(`/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/query-test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getKnowledgeQueryParams(knowledgeBaseId, userId) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/query-params?user_id=${encodeURIComponent(userId)}`,
  )
}

export function updateKnowledgeQueryParams(knowledgeBaseId, payload) {
  return request(`/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/query-params`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function uploadKnowledgeDocument(knowledgeBaseId, userId, file) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(
    `${API_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/documents?user_id=${encodeURIComponent(userId)}`,
    {
      method: 'POST',
      headers: authHeaders(),
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

export async function uploadEvaluationDataset(knowledgeBaseId, userId, file, name, description = '') {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('name', name)
  formData.append('description', description)
  formData.append('user_id', userId)

  const response = await fetch(
    `${API_BASE}/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/evaluation/datasets/upload`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: formData,
    },
  )

  if (!response.ok) {
    throw new Error(await getResponseError(response))
  }

  return response.json()
}

export function generateEvaluationDataset(knowledgeBaseId, payload) {
  return request(`/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/evaluation/datasets/generate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listEvaluationDatasets(knowledgeBaseId, userId) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/evaluation/datasets?user_id=${encodeURIComponent(userId)}`,
  )
}

export function getEvaluationDataset(knowledgeBaseId, datasetId, userId) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/evaluation/datasets/${encodeURIComponent(datasetId)}?user_id=${encodeURIComponent(userId)}`,
  )
}

export function deleteEvaluationDataset(datasetId, userId) {
  return request(`/evaluation/datasets/${encodeURIComponent(datasetId)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })
}

export function runKnowledgeEvaluation(knowledgeBaseId, payload) {
  return request(`/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/evaluation/runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listEvaluationRuns(knowledgeBaseId, userId) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/evaluation/runs?user_id=${encodeURIComponent(userId)}`,
  )
}

export function getEvaluationRun(knowledgeBaseId, runId, userId, errorOnly = false) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/evaluation/runs/${encodeURIComponent(runId)}?user_id=${encodeURIComponent(userId)}&error_only=${errorOnly ? 'true' : 'false'}`,
  )
}

export function deleteEvaluationRun(knowledgeBaseId, runId, userId) {
  return request(
    `/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/evaluation/runs/${encodeURIComponent(runId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  )
}

export async function sendChatStream(message, userId, conversationId = null, handlers = {}, files = [], modelSpec = null) {
  const hasFiles = Array.isArray(files) && files.length > 0
  const requestOptions = hasFiles
    ? {
        method: 'POST',
        body: buildChatFormData(message, userId, conversationId, files, modelSpec),
      }
    : {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, user_id: userId, conversation_id: conversationId, model_spec: modelSpec }),
      }

  requestOptions.headers = authHeaders(requestOptions.headers || {})
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

export async function createChatRun(
  message,
  userId,
  conversationId = null,
  files = [],
  modelSpec = null,
  requestId = null,
) {
  const formData = buildChatFormData(message, userId, conversationId, files, modelSpec)
  if (requestId) formData.append('request_id', requestId)
  const response = await fetch(`${API_BASE}/chat/runs`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })
  if (!response.ok) throw new Error(await getResponseError(response))
  return response.json()
}

export function getChatRun(runId, userId) {
  return request(`/chat/runs/${encodeURIComponent(runId)}?user_id=${encodeURIComponent(userId)}`)
}

export function getConversationActiveRun(conversationId, userId) {
  return request(
    `/chat/conversations/${encodeURIComponent(conversationId)}/active-run?user_id=${encodeURIComponent(userId)}`,
  )
}

export async function streamChatRunEvents(runId, userId, afterId = '0-0', onEvent = () => {}) {
  const headers = authHeaders()
  if (afterId && afterId !== '0-0') headers['Last-Event-ID'] = afterId
  const response = await fetch(
    `${API_BASE}/chat/runs/${encodeURIComponent(runId)}/events?user_id=${encodeURIComponent(userId)}`,
    { headers },
  )
  if (!response.ok || !response.body) throw new Error(await getResponseError(response))

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let lastEventId = afterId || '0-0'
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      const parsed = parseRunStreamEvent(block)
      if (!parsed) continue
      if (parsed.eventId) lastEventId = parsed.eventId
      onEvent(parsed.event, lastEventId)
    }
  }
  if (buffer.trim()) {
    const parsed = parseRunStreamEvent(buffer)
    if (parsed) {
      if (parsed.eventId) lastEventId = parsed.eventId
      onEvent(parsed.event, lastEventId)
    }
  }
  return lastEventId
}

function buildChatFormData(message, userId, conversationId, files, modelSpec = null) {
  const formData = new FormData()
  formData.append('message', message)
  formData.append('user_id', userId)
  if (modelSpec) {
    formData.append('model_spec', modelSpec)
  }
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

function parseRunStreamEvent(rawEvent) {
  const lines = rawEvent.split('\n')
  const data = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')
  if (!data) return null
  const idLine = lines.find((line) => line.startsWith('id:'))
  return {
    eventId: idLine ? idLine.slice(3).trim() : '',
    event: JSON.parse(data),
  }
}
