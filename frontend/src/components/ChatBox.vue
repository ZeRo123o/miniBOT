<script setup>
import { ref } from 'vue'
import { sendChat } from '../apis/resources'
import { selectionStore } from '../stores/selectionStore'

const input = ref('')
const messages = ref([])
const sending = ref(false)

async function submit() {
  const text = input.value.trim()
  if (!text || sending.value) return
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  sending.value = true
  try {
    const response = await sendChat(text, selectionStore.userKey)
    messages.value.push({ role: 'assistant', content: response.answer })
  } catch (error) {
    messages.value.push({ role: 'assistant', content: error.message })
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
      <p v-if="!messages.length" class="empty">保存选择后，可以在这里测试按 name 解析资源的 LangGraph 流程。</p>
      <article v-for="(message, index) in messages" :key="index" :class="message.role">
        <b>{{ message.role }}</b>
        <p>{{ message.content }}</p>
      </article>
    </div>

    <form class="chat-form" @submit.prevent="submit">
      <input v-model="input" placeholder="输入一条消息" />
      <button type="submit">发送</button>
    </form>
  </section>
</template>
