<script setup>
import { ref } from 'vue'
import { sendChat } from '../apis/resources'
import { activeMessages, applyChatResponse, conversationStore } from '../stores/conversationStore'
import { selectionStore } from '../stores/selectionStore'

const input = ref('')
const sending = ref(false)
const errorMessage = ref('')

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
  }
}
</script>

<template>
  <section class="panel chat-panel">
    <header class="panel-header">
      <h2>运行测试</h2>
      <span>{{ sending ? '发送中' : '就绪' }}</span>
    </header>

    <div class="messages">
      <p v-if="!activeMessages.length" class="empty">
        输入消息后，会话和消息会保存到 PostgreSQL，并显示在左侧对话历史中。
      </p>
      <article v-for="message in activeMessages" :key="message.id" :class="message.role">
        <b>{{ message.role }}</b>
        <p>{{ message.content }}</p>
      </article>
      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
    </div>

    <form class="chat-form" @submit.prevent="submit">
      <input v-model="input" placeholder="输入一条消息" />
      <button type="submit" :disabled="sending">发送</button>
    </form>
  </section>
</template>
