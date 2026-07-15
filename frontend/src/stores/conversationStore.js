import { computed, reactive } from 'vue'
import {
  createChatRun,
  deleteConversation,
  getChatRun,
  getConversationActiveRun,
  listConversationMessages,
  listConversations,
  streamChatRunEvents,
  updateConversation,
} from '../apis/resources'

const ACTIVE_RUN_STATUSES = new Set(['pending', 'running'])
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled', 'interrupted'])
const runSubscriptions = new Map()

export const conversationStore = reactive({
  conversations: [],
  messagesByConversationId: {},
  runsByConversationId: {},
  activeId: null,
  loading: false,
  error: '',
})

export const activeConversation = computed(() =>
  conversationStore.conversations.find((item) => item.id === conversationStore.activeId),
)

export const activeMessages = computed(() => {
  if (!conversationStore.activeId) return []
  return conversationStore.messagesByConversationId[conversationStore.activeId] || []
})

export const activeRun = computed(() => {
  if (!conversationStore.activeId) return null
  return conversationStore.runsByConversationId[conversationStore.activeId] || null
})

export const activeConversationIsRunning = computed(() =>
  ACTIVE_RUN_STATUSES.has(activeRun.value?.status),
)

function createTemporaryId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function upsertConversation(conversation) {
  const index = conversationStore.conversations.findIndex((item) => item.id === conversation.id)
  if (index === -1) {
    conversationStore.conversations.unshift(conversation)
  } else {
    conversationStore.conversations[index] = conversation
  }
  conversationStore.conversations.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
}

function removeLocalConversation(conversationId) {
  conversationStore.conversations = conversationStore.conversations.filter((item) => item.id !== conversationId)
  delete conversationStore.messagesByConversationId[conversationId]
}

export async function loadConversations(userId) {
  conversationStore.loading = true
  conversationStore.error = ''
  try {
    conversationStore.conversations = await listConversations(userId)
    if (!conversationStore.activeId && conversationStore.conversations.length) {
      conversationStore.activeId = conversationStore.conversations[0].id
    }
    if (conversationStore.activeId) {
      await loadMessages(conversationStore.activeId, userId)
      await resumeConversationRun(conversationStore.activeId, userId)
    }
  } catch (error) {
    conversationStore.error = error.message
  } finally {
    conversationStore.loading = false
  }
}

export function newConversation() {
  conversationStore.activeId = null
  conversationStore.error = ''
}

export async function selectConversation(id, userId) {
  conversationStore.activeId = id
  await loadMessages(id, userId)
  await resumeConversationRun(id, userId)
}

export async function loadMessages(conversationId, userId) {
  conversationStore.loading = true
  conversationStore.error = ''
  try {
    const messages = await listConversationMessages(
      conversationId,
      userId,
    )
    const currentMessages = conversationStore.messagesByConversationId[conversationId] || []
    const pendingAssistant = currentMessages.find(
      (message) => message.role === 'assistant' && (message.metadata?.loading || message.metadata?.streaming),
    )
    const runState = conversationStore.runsByConversationId[conversationId]
    conversationStore.messagesByConversationId[conversationId] = pendingAssistant && ACTIVE_RUN_STATUSES.has(runState?.status)
      ? [...messages, pendingAssistant]
      : messages
  } catch (error) {
    conversationStore.error = error.message
  } finally {
    conversationStore.loading = false
  }
}

export async function renameConversation(conversationId, userId, title) {
  const nextTitle = title.trim()
  if (!nextTitle) return

  conversationStore.loading = true
  conversationStore.error = ''
  try {
    const conversation = await updateConversation(conversationId, userId, { title: nextTitle })
    upsertConversation(conversation)
  } catch (error) {
    conversationStore.error = error.message
  } finally {
    conversationStore.loading = false
  }
}

export async function removeConversation(conversationId, userId) {
  conversationStore.loading = true
  conversationStore.error = ''
  try {
    await deleteConversation(conversationId, userId)
    const wasActive = conversationStore.activeId === conversationId
    removeLocalConversation(conversationId)
    if (wasActive) {
      conversationStore.activeId = null
    }
  } catch (error) {
    conversationStore.error = error.message
  } finally {
    conversationStore.loading = false
  }
}

export function addPendingChatMessage(content, uploads = [], requestId = createTemporaryId('request')) {
  const conversationId = conversationStore.activeId || createTemporaryId('pending-conversation')
  const now = new Date().toISOString()

  conversationStore.activeId = conversationId
  conversationStore.messagesByConversationId[conversationId] = [
    ...(conversationStore.messagesByConversationId[conversationId] || []),
    {
      id: createTemporaryId('pending-user'),
      role: 'user',
      content,
      created_at: now,
      metadata: { pending: true, uploads, request_id: requestId },
    },
    {
      id: createTemporaryId('pending-assistant'),
      role: 'assistant',
      content: '',
      created_at: now,
      metadata: { pending: true, loading: true, request_id: requestId },
    },
  ]

  return conversationId
}

export function removePendingAssistantMessage(conversationId) {
  const messages = conversationStore.messagesByConversationId[conversationId]
  if (!messages) return

  conversationStore.messagesByConversationId[conversationId] = messages.filter(
    (message) => !message.metadata?.loading,
  )
}

export function applyStreamConversation(event, optimisticConversationId = null) {
  if (event.conversation) {
    upsertConversation(event.conversation)
  }
  if (!event.conversation_id) return

  const currentMessages = conversationStore.messagesByConversationId[optimisticConversationId] || []
  conversationStore.activeId = event.conversation_id
  if (optimisticConversationId && optimisticConversationId !== event.conversation_id) {
    conversationStore.messagesByConversationId[event.conversation_id] = currentMessages
    delete conversationStore.messagesByConversationId[optimisticConversationId]
  }
}

export function appendPendingAssistantContent(conversationId, content) {
  const messages = conversationStore.messagesByConversationId[conversationId]
  if (!messages) return

  const loadingMessage = messages.find((message) => message.metadata?.loading || message.metadata?.streaming)
  if (!loadingMessage) return

  loadingMessage.content += content
  loadingMessage.metadata = {
    ...loadingMessage.metadata,
    loading: false,
    streaming: true,
  }
}

export function appendPendingToolEvent(conversationId, event) {
  const messages = conversationStore.messagesByConversationId[conversationId]
  if (!messages) return

  const loadingMessage = messages.find((message) => message.metadata?.loading || message.metadata?.streaming)
  if (!loadingMessage) return

  const toolCalls = [...(loadingMessage.metadata?.tool_calls || [])]
  if (event.type === 'tool_event') {
    mergeToolCall(toolCalls, event.event || {})
  } else if (event.type === 'subagent_status') {
    mergeSubagentStatus(toolCalls, event)
  }
  loadingMessage.metadata = {
    ...loadingMessage.metadata,
    tool_calls: toolCalls,
  }
}

export function appendPendingSubagentToken(conversationId, event) {
  const messages = conversationStore.messagesByConversationId[conversationId]
  if (!messages || !event.child_thread_id || !event.content) return

  const loadingMessage = messages.find((message) => message.metadata?.loading || message.metadata?.streaming)
  if (!loadingMessage) return

  const toolCalls = [...(loadingMessage.metadata?.tool_calls || [])]
  const task = toolCalls.find((item) => item.id === event.tool_call_id)
  if (!task) return
  const subagents = { ...(task.subagents || {}) }
  const previous = subagents[event.child_thread_id] || emptySubagent(event)
  subagents[event.child_thread_id] = {
    ...previous,
    status: previous.status === 'completed' ? previous.status : 'running',
    text: `${previous.text}${event.content}`,
  }
  task.subagents = subagents
  loadingMessage.metadata = {
    ...loadingMessage.metadata,
    tool_calls: toolCalls,
  }
}

function mergeToolCall(toolCalls, toolCall) {
  if (toolCall.parent_tool_call_id) {
    const task = toolCalls.find((item) => item.id === toolCall.parent_tool_call_id)
    if (!task) return
    const subagents = { ...(task.subagents || {}) }
    const childThreadId = toolCall.child_thread_id || 'child'
    const subagent = subagents[childThreadId] || emptySubagent(toolCall)
    const childCalls = [...(subagent.toolCalls || [])]
    upsertToolCall(childCalls, toolCall)
    subagents[childThreadId] = { ...subagent, toolCalls: childCalls }
    task.subagents = subagents
    return
  }
  upsertToolCall(toolCalls, toolCall)
}

function upsertToolCall(toolCalls, toolCall) {
  const index = toolCalls.findIndex((item) => item.id === toolCall.id)
  if (index >= 0) toolCalls[index] = { ...toolCalls[index], ...toolCall }
  else toolCalls.push({ ...toolCall, subagents: {} })
}

function mergeSubagentStatus(toolCalls, event) {
  const task = toolCalls.find((item) => item.id === event.tool_call_id)
  if (!task || !event.child_thread_id) return
  const subagents = { ...(task.subagents || {}) }
  const previous = subagents[event.child_thread_id] || emptySubagent(event)
  subagents[event.child_thread_id] = {
    ...previous,
    type: event.subagent_type || previous.type,
    runId: event.run_id || previous.runId,
    status: event.status || previous.status,
    error: event.error || '',
  }
  task.subagents = subagents
}

function emptySubagent(event) {
  return {
    childThreadId: event.child_thread_id,
    type: event.subagent_type || 'general',
    runId: event.run_id || '',
    status: event.status || 'running',
    text: '',
    error: '',
    toolCalls: [],
  }
}

export function applyChatResponse(response, optimisticConversationId = null, activate = true) {
  if (response.conversation) {
    upsertConversation(response.conversation)
  }
  if (response.conversation_id) {
    if (activate) conversationStore.activeId = response.conversation_id
    conversationStore.messagesByConversationId[response.conversation_id] = response.messages || []
    if (optimisticConversationId && optimisticConversationId !== response.conversation_id) {
      delete conversationStore.messagesByConversationId[optimisticConversationId]
    }
  }
}

function createClientRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return createTemporaryId('chat-request')
}

function ensurePendingAssistant(conversationId, runId, requestId = '') {
  const messages = conversationStore.messagesByConversationId[conversationId] || []
  const existing = messages.find(
    (message) => message.role === 'assistant' && (message.metadata?.loading || message.metadata?.streaming),
  )
  if (existing) {
    existing.metadata = { ...existing.metadata, run_id: runId, request_id: requestId || existing.metadata?.request_id }
    return existing
  }
  const message = {
    id: createTemporaryId('pending-assistant'),
    role: 'assistant',
    content: '',
    created_at: new Date().toISOString(),
    metadata: { pending: true, loading: true, run_id: runId, request_id: requestId },
  }
  conversationStore.messagesByConversationId[conversationId] = [...messages, message]
  return message
}

function applyRunCreated(response, optimisticConversationId) {
  if (response.conversation) upsertConversation(response.conversation)
  const conversationId = response.conversation_id
  const messages = conversationStore.messagesByConversationId[optimisticConversationId] || []
  if (optimisticConversationId !== conversationId) {
    conversationStore.messagesByConversationId[conversationId] = messages
    delete conversationStore.messagesByConversationId[optimisticConversationId]
  }
  if (conversationStore.activeId === optimisticConversationId) conversationStore.activeId = conversationId
  ensurePendingAssistant(conversationId, response.run_id, response.request_id)
  conversationStore.runsByConversationId[conversationId] = {
    runId: response.run_id,
    requestId: response.request_id,
    status: response.status || 'pending',
    lastEventId: '0-0',
    error: '',
  }
  return conversationId
}

function handleRunEvent(conversationId, event, eventId) {
  const runState = conversationStore.runsByConversationId[conversationId]
  if (!runState) return
  if (eventId) runState.lastEventId = eventId

  if (event.type === 'token') {
    ensurePendingAssistant(conversationId, runState.runId, runState.requestId)
    appendPendingAssistantContent(conversationId, event.content || '')
  } else if (event.type === 'tool_event' || event.type === 'subagent_status') {
    ensurePendingAssistant(conversationId, runState.runId, runState.requestId)
    appendPendingToolEvent(conversationId, event)
  } else if (event.type === 'subagent_token') {
    ensurePendingAssistant(conversationId, runState.runId, runState.requestId)
    appendPendingSubagentToken(conversationId, event)
  } else if (event.type === 'done') {
    applyChatResponse(event, null, false)
  } else if (event.type === 'error') {
    runState.error = event.detail || '回答生成失败。'
  } else if (event.type === 'end') {
    runState.status = event.status || 'completed'
  }
}

function subscribeConversationRun(conversationId, userId, runId) {
  const existing = runSubscriptions.get(conversationId)
  if (existing?.runId === runId) return existing.promise

  const promise = (async () => {
    while (true) {
      const runState = conversationStore.runsByConversationId[conversationId]
      if (!runState || runState.runId !== runId || TERMINAL_RUN_STATUSES.has(runState.status)) return
      let sawTerminalEvent = false
      try {
        await streamChatRunEvents(runId, userId, runState.lastEventId, (event, eventId) => {
          handleRunEvent(conversationId, event, eventId)
          if (event.type === 'end') sawTerminalEvent = true
        })
      } catch (error) {
        runState.error = error.message
      }

      let response
      try {
        response = await getChatRun(runId, userId)
      } catch (error) {
        runState.error = error.message
        await new Promise((resolve) => setTimeout(resolve, 1000))
        continue
      }
      const status = response.run?.status || 'failed'
      runState.status = status
      if (TERMINAL_RUN_STATUSES.has(status) || sawTerminalEvent) {
        await loadMessages(conversationId, userId)
        return
      }
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  })().finally(() => {
    if (runSubscriptions.get(conversationId)?.runId === runId) runSubscriptions.delete(conversationId)
  })
  runSubscriptions.set(conversationId, { runId, promise })
  return promise
}

export async function startConversationRun({
  content,
  userId,
  files = [],
  modelSpec,
  optimisticUploads = [],
}) {
  const requestId = createClientRequestId()
  const originalConversationId = conversationStore.activeId
  const optimisticConversationId = addPendingChatMessage(content, optimisticUploads, requestId)
  try {
    const response = await createChatRun(
      content,
      userId,
      originalConversationId,
      files,
      modelSpec,
      requestId,
    )
    const conversationId = applyRunCreated(response, optimisticConversationId)
    void subscribeConversationRun(conversationId, userId, response.run_id)
    return response
  } catch (error) {
    removePendingAssistantMessage(optimisticConversationId)
    throw error
  }
}

export async function resumeConversationRun(conversationId, userId) {
  if (!conversationId || String(conversationId).startsWith('pending-conversation')) return null
  const response = await getConversationActiveRun(conversationId, userId)
  const run = response.run
  if (!run) return null
  const previous = conversationStore.runsByConversationId[conversationId]
  conversationStore.runsByConversationId[conversationId] = {
    runId: run.id,
    requestId: run.request_id,
    status: run.status,
    lastEventId: previous?.runId === run.id ? previous.lastEventId : '0-0',
    error: previous?.runId === run.id ? previous.error : '',
  }
  ensurePendingAssistant(conversationId, run.id, run.request_id)
  void subscribeConversationRun(conversationId, userId, run.id)
  return run
}
