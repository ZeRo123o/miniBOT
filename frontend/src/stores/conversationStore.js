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
  activeMode: 'assistant',
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

export async function loadConversations(userKey) {
  conversationStore.loading = true
  conversationStore.error = ''
  try {
    conversationStore.conversations = await listConversations(userKey)
    if (!conversationStore.activeId && conversationStore.conversations.length) {
      conversationStore.activeId = conversationStore.conversations[0].id
    }
    if (conversationStore.activeId) {
      await loadMessages(conversationStore.activeId, userKey)
      conversationStore.activeMode = inferModeFromMessages(
        conversationStore.messagesByConversationId[conversationStore.activeId],
      )
    }
  } catch (error) {
    conversationStore.error = error.message
  } finally {
    conversationStore.loading = false
  }
}

export function newConversation() {
  conversationStore.activeId = null
  conversationStore.activeMode = 'assistant'
  conversationStore.error = ''
}

export async function selectConversation(id, userKey) {
  conversationStore.activeId = id
  await loadMessages(id, userKey)
  conversationStore.activeMode = inferModeFromMessages(conversationStore.messagesByConversationId[id])
}

export async function loadMessages(conversationId, userKey) {
  conversationStore.loading = true
  conversationStore.error = ''
  try {
    conversationStore.messagesByConversationId[conversationId] = await listConversationMessages(
      conversationId,
      userKey,
    )
  } catch (error) {
    conversationStore.error = error.message
  } finally {
    conversationStore.loading = false
  }
}

export async function renameConversation(conversationId, userKey, title) {
  const nextTitle = title.trim()
  if (!nextTitle) return

  conversationStore.loading = true
  conversationStore.error = ''
  try {
    const conversation = await updateConversation(conversationId, userKey, { title: nextTitle })
    upsertConversation(conversation)
  } catch (error) {
    conversationStore.error = error.message
  } finally {
    conversationStore.loading = false
  }
}

export async function removeConversation(conversationId, userKey) {
  conversationStore.loading = true
  conversationStore.error = ''
  try {
    await deleteConversation(conversationId, userKey)
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

export function setActiveMode(mode) {
  conversationStore.activeMode = mode
}

export function addPendingChatMessage(content, mode = conversationStore.activeMode) {
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
      metadata: { pending: true, mode },
    },
    {
      id: createTemporaryId('pending-assistant'),
      role: 'assistant',
      content: '',
      created_at: now,
      metadata: { pending: true, loading: true, mode },
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
  if (event.mode) {
    conversationStore.activeMode = event.mode
  }
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

export function applyChatResponse(response, optimisticConversationId = null) {
  if (response.mode) {
    conversationStore.activeMode = response.mode
  }
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

function inferModeFromMessages(messages = []) {
  const mode = [...messages]
    .reverse()
    .map((message) => message.metadata?.mode)
    .find((item) => item === 'assistant' || item === 'knowledge')
  return mode || 'assistant'
}
