<script setup>
import { Bot, BookOpenText, SendHorizontal } from 'lucide-vue-next'
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
  setActiveMode,
} from '../stores/conversationStore'
import { selectionStore } from '../stores/selectionStore'
import MarkdownMessage from './MarkdownMessage.vue'

const input = ref('')
const inputEl = ref(null)
const messagesEl = ref(null)
const sending = ref(false)
const errorMessage = ref('')
const chatModes = [
  {
    value: 'assistant',
    label: '智能助手',
    description: '调用工具、MCP、Skill 和上下文资源完成任务。',
    icon: Bot,
  },
  {
    value: 'knowledge',
    label: '知识问答',
    description: '面向企业知识库检索和引用来源回答。',
    icon: BookOpenText,
  },
]

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
  const mode = conversationStore.activeMode
  const optimisticConversationId = addPendingChatMessage(text, mode)
  let streamConversationId = optimisticConversationId
  scrollToBottom()

  try {
    await sendChatStream(text, selectionStore.userKey, conversationId, mode, {
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
        <div class="chat-mode-switch" aria-label="选择对话模式">
          <button
            v-for="mode in chatModes"
            :key="mode.value"
            type="button"
            class="chat-mode-option"
            :class="{ active: conversationStore.activeMode === mode.value }"
            @click="setActiveMode(mode.value)"
          >
            <component :is="mode.icon" :size="18" />
            <span>{{ mode.label }}</span>
          </button>
        </div>
        <p>{{ chatModes.find((mode) => mode.value === conversationStore.activeMode)?.description }}</p>
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
