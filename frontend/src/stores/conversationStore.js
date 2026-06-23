import { computed, reactive } from 'vue'
import {
  deleteConversation,
  listConversationMessages,
  listConversations,
  updateConversation,
} from '../apis/resources'

export const conversationStore = reactive({
  conversations: [],
  messagesByConversationId: {},
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
}

export async function loadMessages(conversationId, userId) {
  conversationStore.loading = true
  conversationStore.error = ''
  try {
    const messages = await listConversationMessages(
      conversationId,
      userId,
    )
    conversationStore.messagesByConversationId[conversationId] = messages
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

export function addPendingChatMessage(content, uploads = []) {
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
      metadata: { pending: true, uploads },
    },
    {
      id: createTemporaryId('pending-assistant'),
      role: 'assistant',
      content: '',
      created_at: now,
      metadata: { pending: true, loading: true },
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

export function applyChatResponse(response, optimisticConversationId = null) {
  if (response.conversation) {
    upsertConversation(response.conversation)
  }
  if (response.conversation_id) {
    conversationStore.activeId = response.conversation_id
    conversationStore.messagesByConversationId[response.conversation_id] = response.messages || []
    if (optimisticConversationId && optimisticConversationId !== response.conversation_id) {
      delete conversationStore.messagesByConversationId[optimisticConversationId]
    }
  }
}
