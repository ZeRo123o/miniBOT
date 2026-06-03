<script setup>
import { computed, onMounted, ref } from 'vue'
import { FileText, Loader2, Plus, Search, UploadCloud, X } from 'lucide-vue-next'
import {
  createKnowledgeBase,
  listKnowledgeBases,
  listKnowledgeDocuments,
  uploadKnowledgeDocument,
} from '../apis/resources'
import { selectionStore } from '../stores/selectionStore'

const knowledgeTypes = ['全部类型', '文档知识库', '知识图谱']
const acceptedTypes = '.md,.markdown,.txt,.pdf,.docx,.xlsx,.csv'

const searchText = ref('')
const knowledgeBases = ref([])
const documentsByBaseId = ref({})
const selectedBaseId = ref(null)
const loading = ref(false)
const errorMessage = ref('')

const dialogOpen = ref(false)
const form = ref({
  name: '',
  description: '',
  file: null,
})
const submitting = ref(false)
const submitMessage = ref('')

const filteredKnowledgeBases = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  if (!keyword) return knowledgeBases.value
  return knowledgeBases.value.filter((item) => {
    return [item.name, item.description].some((value) => String(value || '').toLowerCase().includes(keyword))
  })
})

const selectedKnowledgeBase = computed(() =>
  knowledgeBases.value.find((item) => item.id === selectedBaseId.value),
)

const selectedDocuments = computed(() => documentsByBaseId.value[selectedBaseId.value] || [])

onMounted(() => {
  loadKnowledgeBases()
})

async function loadKnowledgeBases() {
  loading.value = true
  errorMessage.value = ''
  try {
    knowledgeBases.value = await listKnowledgeBases(selectionStore.userKey)
    if (!selectedBaseId.value && knowledgeBases.value.length) {
      selectedBaseId.value = knowledgeBases.value[0].id
      await loadDocuments(selectedBaseId.value)
    }
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    loading.value = false
  }
}

async function loadDocuments(knowledgeBaseId) {
  if (!knowledgeBaseId) return
  documentsByBaseId.value = {
    ...documentsByBaseId.value,
    [knowledgeBaseId]: await listKnowledgeDocuments(knowledgeBaseId, selectionStore.userKey),
  }
}

async function selectKnowledgeBase(knowledgeBaseId) {
  selectedBaseId.value = knowledgeBaseId
  if (!documentsByBaseId.value[knowledgeBaseId]) {
    await loadDocuments(knowledgeBaseId)
  }
}

function openCreateDialog() {
  form.value = {
    name: '',
    description: '',
    file: null,
  }
  submitMessage.value = ''
  errorMessage.value = ''
  dialogOpen.value = true
}

function closeCreateDialog() {
  if (submitting.value) return
  dialogOpen.value = false
}

function handleFileChange(event) {
  form.value.file = event.target.files?.[0] || null
}

async function submitKnowledgeBase() {
  const name = form.value.name.trim()
  if (!name || !form.value.file || submitting.value) return

  submitting.value = true
  submitMessage.value = '正在创建知识库...'
  errorMessage.value = ''

  try {
    const knowledgeBase = await createKnowledgeBase({
      name,
      description: form.value.description.trim(),
      user_key: selectionStore.userKey,
    })
    selectedBaseId.value = knowledgeBase.id
    submitMessage.value = '正在上传并解析文档...'
    await uploadKnowledgeDocument(knowledgeBase.id, selectionStore.userKey, form.value.file)
    await loadKnowledgeBases()
    await loadDocuments(knowledgeBase.id)
    selectedBaseId.value = knowledgeBase.id
    dialogOpen.value = false
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    submitting.value = false
    submitMessage.value = ''
  }
}

function formatFileSize(size) {
  if (!size) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = size
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

function statusText(status) {
  const statusMap = {
    uploaded: '已上传',
    parsing: '解析中',
    parsed: '已解析',
    chunking: '分块中',
    chunked: '已分块',
    embedding: '向量化中',
    indexed: '已入库',
    failed: '解析失败',
  }
  return statusMap[status] || status || '未知'
}
</script>

<template>
  <section class="knowledge-page">
    <header class="knowledge-header">
      <div class="knowledge-title-row">
        <h1>知识库</h1>
        <div class="knowledge-tabs" aria-label="知识库类型">
          <button type="button" class="active">文档知识库</button>
          <button type="button">知识图谱</button>
        </div>
      </div>
    </header>

    <div class="knowledge-toolbar">
      <label class="knowledge-search">
        <Search :size="16" />
        <input v-model="searchText" type="search" placeholder="搜索知识库..." />
      </label>
      <select aria-label="知识库类型筛选">
        <option v-for="type in knowledgeTypes" :key="type">{{ type }}</option>
      </select>
      <span />
      <button type="button" class="knowledge-create-button" @click="openCreateDialog">
        <Plus :size="16" />
        <span>新建知识库</span>
      </button>
    </div>

    <div v-if="loading" class="knowledge-empty-state">
      <Loader2 class="spin" :size="28" />
      <p>正在加载知识库</p>
    </div>

    <div v-else-if="!knowledgeBases.length" class="knowledge-empty-state">
      <h2>暂无知识库</h2>
      <p>创建您的第一个知识库，开始管理文档和知识</p>
      <button type="button" class="knowledge-primary-button" @click="openCreateDialog">
        <Plus :size="16" />
        <span>创建知识库</span>
      </button>
    </div>

    <div v-else class="knowledge-content">
      <aside class="knowledge-list" aria-label="知识库列表">
        <button
          v-for="item in filteredKnowledgeBases"
          :key="item.id"
          type="button"
          class="knowledge-card"
          :class="{ active: item.id === selectedBaseId }"
          @click="selectKnowledgeBase(item.id)"
        >
          <strong>{{ item.name }}</strong>
          <span>{{ item.description || '暂无描述' }}</span>
        </button>
      </aside>

      <main class="knowledge-detail">
        <div class="knowledge-detail-header">
          <div>
            <h2>{{ selectedKnowledgeBase?.name || '请选择知识库' }}</h2>
            <p>{{ selectedKnowledgeBase?.description || '上传文档后会自动转为 Markdown 并保存解析状态。' }}</p>
          </div>
          <button type="button" class="knowledge-create-button" @click="openCreateDialog">
            <UploadCloud :size="16" />
            <span>上传新文档</span>
          </button>
        </div>

        <div v-if="selectedDocuments.length" class="knowledge-document-list">
          <article v-for="document in selectedDocuments" :key="document.id" class="knowledge-document-row">
            <FileText :size="20" />
            <div>
              <strong>{{ document.filename }}</strong>
              <span>{{ formatFileSize(document.file_size) }}</span>
            </div>
            <em :class="['document-status', document.status]">{{ statusText(document.status) }}</em>
          </article>
        </div>
        <div v-else class="knowledge-document-empty">
          <FileText :size="34" />
          <p>当前知识库还没有文档</p>
        </div>
      </main>
    </div>

    <p v-if="errorMessage" class="knowledge-error">{{ errorMessage }}</p>

    <div v-if="dialogOpen" class="modal-backdrop" @click.self="closeCreateDialog">
      <section class="knowledge-upload-dialog" role="dialog" aria-modal="true" aria-labelledby="knowledge-upload-title">
        <header>
          <div>
            <h2 id="knowledge-upload-title">创建知识库</h2>
            <p>上传文档后，后端会保存原始文件、转换 Markdown 并记录解析状态。</p>
          </div>
          <button type="button" class="dialog-close-button" :disabled="submitting" @click="closeCreateDialog">
            <X :size="18" />
          </button>
        </header>

        <form class="knowledge-upload-form" @submit.prevent="submitKnowledgeBase">
          <label>
            <span>知识库名称</span>
            <input v-model="form.name" type="text" maxlength="255" placeholder="例如：公司制度文档" required />
          </label>

          <label>
            <span>描述</span>
            <textarea v-model="form.description" rows="3" placeholder="记录知识库用途或文档范围" />
          </label>

          <label class="file-drop-zone">
            <UploadCloud :size="28" />
            <strong>{{ form.file?.name || '选择要上传的文档' }}</strong>
            <span>{{ form.file ? formatFileSize(form.file.size) : '支持 md、txt、pdf、docx、xlsx、csv' }}</span>
            <input :accept="acceptedTypes" type="file" required @change="handleFileChange" />
          </label>

          <p v-if="submitMessage" class="upload-status">
            <Loader2 class="spin" :size="16" />
            <span>{{ submitMessage }}</span>
          </p>

          <div class="dialog-actions">
            <button type="button" class="secondary-button" :disabled="submitting" @click="closeCreateDialog">
              取消
            </button>
            <button type="submit" class="knowledge-primary-button" :disabled="submitting || !form.name.trim() || !form.file">
              <Loader2 v-if="submitting" class="spin" :size="16" />
              <Plus v-else :size="16" />
              <span>{{ submitting ? '处理中' : '创建并上传' }}</span>
            </button>
          </div>
        </form>
      </section>
    </div>
  </section>
</template>
