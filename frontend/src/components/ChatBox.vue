<script setup>
import { Paperclip, Plus, SendHorizontal, X } from 'lucide-vue-next'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { loadModelProviderWorkspace, modelProviderStore } from '../stores/modelProviderStore'
import {
  activeConversationIsRunning,
  activeMessages,
  activeRun,
  startConversationRun,
} from '../stores/conversationStore'
import { selectionStore } from '../stores/selectionStore'
import AppSelect from './AppSelect.vue'
import MarkdownMessage from './MarkdownMessage.vue'
import ToolCallsGroup from './ToolCallsGroup.vue'

const input = ref('')
const inputEl = ref(null)
const fileInputEl = ref(null)
const messagesEl = ref(null)
const submitting = ref(false)
const sending = computed(() => submitting.value || activeConversationIsRunning.value)
const activeRunError = computed(() => activeRun.value?.error || '')
const errorMessage = ref('')
const selectedFiles = ref([])
const selectedModelSpec = ref('')
const plusMenuOpen = ref(false)

const chatModelOptions = computed(() =>
  Object.values(modelProviderStore.chatModelsByProvider).flatMap((group) =>
    (group.models || []).map((model) => ({
      ...model,
      label: model.display_name || model.id,
      providerLabel: group.provider_display_name || group.provider_id,
    })),
  ),
)

const chatSelectOptions = computed(() => {
  if (!chatModelOptions.value.length) {
    return [{ value: '', label: '未配置模型' }]
  }
  return chatModelOptions.value.map((model) => ({
    value: model.spec,
    label: `${model.providerLabel} / ${model.label}`,
    selectedLabel: model.label,
  }))
})

onMounted(() => {
  loadModelProviderWorkspace()
})

watch(
  chatModelOptions,
  () => {
    if (selectedModelSpec.value && chatModelOptions.value.some((model) => model.spec === selectedModelSpec.value)) {
      return
    }
    selectedModelSpec.value = chatModelOptions.value[0]?.spec || ''
  },
  { immediate: true },
)

watch(activeMessages, () => scrollToBottom(), { deep: true })

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
  if (!selectedModelSpec.value) {
    errorMessage.value = '请先在输入框右侧选择聊天模型'
    return
  }

  input.value = ''
  submitting.value = true
  // 长文本发送后立即恢复单行高度，不等待流式请求结束。
  await resizeInput()
  const filesToSend = [...selectedFiles.value]
  selectedFiles.value = []
  plusMenuOpen.value = false
  errorMessage.value = ''
  const optimisticUploads = filesToSend.map((file) => ({
    file_name: file.name,
    size: file.size,
    content_type: file.type || '',
  }))
  try {
    const runPromise = startConversationRun({
      content: text,
      userId: selectionStore.userId,
      files: filesToSend,
      modelSpec: selectedModelSpec.value,
      optimisticUploads,
    })
    scrollToBottom()
    await runPromise
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    submitting.value = false
    resizeInput()
  }
}

function togglePlusMenu() {
  if (sending.value) return
  plusMenuOpen.value = !plusMenuOpen.value
}

function openFilePicker() {
  if (sending.value) return
  plusMenuOpen.value = false
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

function chartUrls(message) {
  return (message.metadata?.tool_calls || [])
    .map((toolCall) => toolCall.chart_url)
    .filter(Boolean)
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
        <MarkdownMessage
          v-if="!message.metadata?.loading"
          :content="message.content"
          :image-urls="chartUrls(message)"
        />
        <div v-if="message.metadata?.uploads?.length" class="message-attachments">
          <span v-for="upload in message.metadata.uploads" :key="upload.path || upload.file_name" class="attachment-pill">
            <Paperclip :size="13" />
            {{ upload.file_name || upload.path }}
          </span>
        </div>
      </article>
      <p v-if="errorMessage || activeRunError" class="error">{{ errorMessage || activeRunError }}</p>
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
      <div class="chat-plus-wrap">
        <button type="button" class="chat-plus-button" :disabled="sending" title="更多功能" @click="togglePlusMenu">
          <Plus :size="22" />
        </button>
        <div v-if="plusMenuOpen" class="chat-plus-menu">
          <button type="button" class="chat-plus-menu-item" @click="openFilePicker">
            <Paperclip :size="16" />
            <span>上传附件</span>
          </button>
        </div>
      </div>
      <textarea
        ref="inputEl"
        v-model="input"
        placeholder="询问 MiniBOT"
        rows="1"
        @input="resizeInput"
        @keydown.enter.exact.prevent="submit"
      />
      <AppSelect
        v-model="selectedModelSpec"
        class="chat-model-app-select"
        aria-label="聊天模型"
        :disabled="sending || !chatModelOptions.length"
        menu-align="start"
        :menu-width="260"
        :options="chatSelectOptions"
      />
      <button type="submit" class="chat-send-button" :disabled="sending || !input.trim() || !selectedModelSpec" title="发送">
        <SendHorizontal :size="20" />
      </button>
    </form>
  </section>
</template>
