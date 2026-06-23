<script setup>
import { Paperclip, SendHorizontal, X } from 'lucide-vue-next'
import { nextTick, ref } from 'vue'
import { sendChatStream } from '../apis/resources'
import {
  activeMessages,
  addPendingChatMessage,
  appendPendingAssistantContent,
  appendPendingToolEvent,
  appendPendingSubagentToken,
  applyChatResponse,
  applyStreamConversation,
  conversationStore,
  removePendingAssistantMessage,
} from '../stores/conversationStore'
import { selectionStore } from '../stores/selectionStore'
import MarkdownMessage from './MarkdownMessage.vue'
import ToolCallsGroup from './ToolCallsGroup.vue'

const input = ref('')
const inputEl = ref(null)
const fileInputEl = ref(null)
const messagesEl = ref(null)
const sending = ref(false)
const errorMessage = ref('')
const selectedFiles = ref([])

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
  const filesToSend = [...selectedFiles.value]
  selectedFiles.value = []
  sending.value = true
  errorMessage.value = ''
  const conversationId = conversationStore.activeId
  const optimisticUploads = filesToSend.map((file) => ({
    file_name: file.name,
    size: file.size,
    content_type: file.type || '',
  }))
  const optimisticConversationId = addPendingChatMessage(text, optimisticUploads)
  let streamConversationId = optimisticConversationId
  scrollToBottom()

  try {
    await sendChatStream(
      text,
      selectionStore.userId,
      conversationId,
      {
        conversation(event) {
          applyStreamConversation(event, optimisticConversationId)
          streamConversationId = event.conversation_id
          scrollToBottom()
        },
        token(event) {
          appendPendingAssistantContent(streamConversationId, event.content || '')
          scrollToBottom()
        },
        subagent_token(event) {
          appendPendingSubagentToken(streamConversationId, event)
          scrollToBottom()
        },
        subagent_status(event) {
          appendPendingToolEvent(streamConversationId, event)
          scrollToBottom()
        },
        tool_event(event) {
          appendPendingToolEvent(streamConversationId, event)
          scrollToBottom()
        },
        done(event) {
          applyChatResponse(event, optimisticConversationId)
          scrollToBottom()
        },
      },
      filesToSend,
    )
  } catch (error) {
    removePendingAssistantMessage(streamConversationId)
    errorMessage.value = error.message
  } finally {
    sending.value = false
    resizeInput()
  }
}

function openFilePicker() {
  if (sending.value) return
  fileInputEl.value?.click()
}

function onFilesSelected(event) {
  const files = Array.from(event.target.files || [])
  selectedFiles.value = files.slice(0, 10)
  event.target.value = ''
}

function removeSelectedFile(index) {
  selectedFiles.value.splice(index, 1)
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
        <ToolCallsGroup
          :tool-calls="message.metadata?.tool_calls || []"
          :is-active="Boolean(message.metadata?.loading || message.metadata?.streaming)"
        />
        <MarkdownMessage v-if="!message.metadata?.loading" :content="message.content" />
        <div v-if="message.metadata?.uploads?.length" class="message-attachments">
          <span v-for="upload in message.metadata.uploads" :key="upload.path || upload.file_name" class="attachment-pill">
            <Paperclip :size="13" />
            {{ upload.file_name || upload.path }}
          </span>
        </div>
      </article>
      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
    </div>

    <div v-if="selectedFiles.length" class="selected-attachments">
      <span v-for="(file, index) in selectedFiles" :key="`${file.name}-${file.size}-${index}`" class="attachment-pill">
        <Paperclip :size="13" />
        {{ file.name }}
        <button type="button" class="remove-attachment" @click="removeSelectedFile(index)" title="移除附件">
          <X :size="12" />
        </button>
      </span>
    </div>

    <form class="chat-form" @submit.prevent="submit">
      <input ref="fileInputEl" class="file-input" type="file" multiple @change="onFilesSelected" />
      <button type="button" :disabled="sending" title="添加附件" @click="openFilePicker">
        <Paperclip :size="18" />
      </button>
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
