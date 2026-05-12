<script setup>
import { MessageSquarePlus, MessageSquareText } from 'lucide-vue-next'
import {
  conversationStore,
  newConversation,
  selectConversation,
} from '../stores/conversationStore'
import { selectionStore } from '../stores/selectionStore'
</script>

<template>
  <aside class="conversation-sidebar">
    <button
      class="new-chat-button"
      type="button"
      :disabled="conversationStore.loading"
      @click="newConversation(selectionStore.userKey)"
    >
      <MessageSquarePlus :size="18" />
      <span>发起新对话</span>
    </button>

    <section class="conversation-section">
      <h2>对话历史</h2>
      <p v-if="conversationStore.error" class="conversation-error">
        {{ conversationStore.error }}
      </p>
      <div class="conversation-list">
        <button
          v-for="conversation in conversationStore.conversations"
          :key="conversation.id"
          class="conversation-item"
          :class="{ active: conversation.id === conversationStore.activeId }"
          type="button"
          @click="selectConversation(conversation.id, selectionStore.userKey)"
        >
          <MessageSquareText :size="16" />
          <span>{{ conversation.title }}</span>
        </button>
      </div>
    </section>
  </aside>
</template>
