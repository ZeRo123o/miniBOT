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

export async function selectConversation(id, userKey) {
  conversationStore.activeId = id
  await loadMessages(id, userKey)
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

export function applyChatResponse(response) {
  if (response.conversation) {
    upsertConversation(response.conversation)
  }
  if (response.conversation_id) {
    conversationStore.activeId = response.conversation_id
    conversationStore.messagesByConversationId[response.conversation_id] = response.messages || []
  }
}
