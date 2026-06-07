<script setup>
import { SendHorizontal } from 'lucide-vue-next'
import { nextTick, ref } from 'vue'
import { sendChatStream } from '../apis/resources'
import {
  activeMessages,
  addPendingChatMessage,
  appendPendingAssistantContent,
  applyChatResponse,
  applyStreamConversation,
  conversationStore,
  removePendingAssistantMessage,
} from '../stores/conversationStore'
import { selectionStore } from '../stores/selectionStore'
import MarkdownMessage from './MarkdownMessage.vue'

const input = ref('')
const inputEl = ref(null)
const messagesEl = ref(null)
const sending = ref(false)
const errorMessage = ref('')

async function resizeInput() {
  await nextTick()
  if (!inputEl.value) return
  inputEl.value.style.height = 'auto'
  inputEl.value.style.height = `${Math.min(inputEl.value.scrollHeight, 180)}px`
}

async function scrollToBottom() {
  await nextTick()
  if (!messagesEl.value) return
  messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

async function submit() {
  const text = input.value.trim()
  if (!text || sending.value) return

  input.value = ''
  sending.value = true
  errorMessage.value = ''
  const conversationId = conversationStore.activeId
  const optimisticConversationId = addPendingChatMessage(text)
  let streamConversationId = optimisticConversationId
  scrollToBottom()

  try {
    await sendChatStream(text, selectionStore.userKey, conversationId, {
      conversation(event) {
        applyStreamConversation(event, optimisticConversationId)
        streamConversationId = event.conversation_id
        scrollToBottom()
      },
      token(event) {
        appendPendingAssistantContent(streamConversationId, event.content || '')
        scrollToBottom()
      },
      done(event) {
        applyChatResponse(event, optimisticConversationId)
        scrollToBottom()
      },
    })
  } catch (error) {
    removePendingAssistantMessage(streamConversationId)
    errorMessage.value = error.message
  } finally {
    sending.value = false
    resizeInput()
  }
}
</script>

<template>
  <section class="chat-panel" :class="{ empty: !activeMessages.length }">
    <div ref="messagesEl" class="messages">
      <div v-if="!activeMessages.length" class="chat-empty-state">
        <h2>你好，我是 MiniBOT</h2>
        <p>调用工具、MCP、Skill 和上下文资源完成任务。</p>
      </div>

      <article v-for="message in activeMessages" :key="message.id" :class="['message', message.role]">
        <b v-if="message.role === 'assistant'">MiniBOT</b>
        <div v-if="message.metadata?.loading" class="typing-indicator" aria-label="MiniBOT 正在生成回答">
          <span />
          <span />
          <span />
        </div>
        <MarkdownMessage v-else :content="message.content" />
      </article>
      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
    </div>

    <form class="chat-form" @submit.prevent="submit">
      <textarea
        ref="inputEl"
        v-model="input"
        placeholder="询问 MiniBOT"
        rows="1"
        @input="resizeInput"
        @keydown.enter.exact.prevent="submit"
      />
      <button type="submit" :disabled="sending || !input.trim()" title="发送">
        <SendHorizontal :size="18" />
      </button>
    </form>
  </section>
</template>
