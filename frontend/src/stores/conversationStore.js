import { computed, reactive } from 'vue'
import {
  createConversation,
  listConversationMessages,
  listConversations,
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

export async function newConversation(userKey) {
  conversationStore.loading = true
  conversationStore.error = ''
  try {
    const conversation = await createConversation(userKey)
    upsertConversation(conversation)
    conversationStore.activeId = conversation.id
    conversationStore.messagesByConversationId[conversation.id] = []
  } catch (error) {
    conversationStore.error = error.message
  } finally {
    conversationStore.loading = false
  }
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

export function applyChatResponse(response) {
  if (response.conversation) {
    upsertConversation(response.conversation)
  }
  if (response.conversation_id) {
    conversationStore.activeId = response.conversation_id
    conversationStore.messagesByConversationId[response.conversation_id] = response.messages || []
  }
}
