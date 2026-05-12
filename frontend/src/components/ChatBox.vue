<script setup>
import { SendHorizontal } from 'lucide-vue-next'
import { nextTick, ref } from 'vue'
import { sendChat } from '../apis/resources'
import { activeMessages, applyChatResponse, conversationStore } from '../stores/conversationStore'
import { selectionStore } from '../stores/selectionStore'
import MarkdownMessage from './MarkdownMessage.vue'

const input = ref('')
const inputEl = ref(null)
const sending = ref(false)
const errorMessage = ref('')

async function resizeInput() {
  await nextTick()
  if (!inputEl.value) return
  inputEl.value.style.height = 'auto'
  inputEl.value.style.height = `${Math.min(inputEl.value.scrollHeight, 180)}px`
}

async function submit() {
  const text = input.value.trim()
  if (!text || sending.value) return

  input.value = ''
  sending.value = true
  errorMessage.value = ''

  try {
    const response = await sendChat(text, selectionStore.userKey, conversationStore.activeId)
    applyChatResponse(response)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    sending.value = false
    resizeInput()
  }
}
</script>

<template>
  <section class="chat-panel" :class="{ empty: !activeMessages.length }">
    <div class="messages">
      <div v-if="!activeMessages.length" class="chat-empty-state">
        <h2>你好，我是 MiniBOT</h2>
        <p>输入第一条消息后，系统会创建新对话并保存到左侧历史列表。</p>
      </div>

      <article v-for="message in activeMessages" :key="message.id" :class="['message', message.role]">
        <b v-if="message.role === 'assistant'">MiniBOT</b>
        <MarkdownMessage :content="message.content" />
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
