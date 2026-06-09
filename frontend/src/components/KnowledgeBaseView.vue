<script setup>
import { computed, onMounted, ref } from 'vue'
import { FileText, Loader2, Plus, Search, UploadCloud, X } from 'lucide-vue-next'
import {
  createKnowledgeBase,
  listKnowledgeChunkPresets,
  listKnowledgeBases,
  listKnowledgeDocuments,
  uploadKnowledgeDocument,
} from '../apis/resources'
import { selectionStore } from '../stores/selectionStore'

const knowledgeTypes = ['全部类型', '文档知识库', '知识图谱']
const acceptedTypes = '.md,.markdown,.txt,.pdf,.docx,.xlsx,.csv'

const searchText = ref('')
const knowledgeBases = ref([])
const chunkPresets = ref([])
const documentsByBaseId = ref({})
const selectedBaseId = ref(null)
const loading = ref(false)
const errorMessage = ref('')

const createDialogOpen = ref(false)
const uploadDialogOpen = ref(false)
const createForm = ref({
  name: '',
  description: '',
  chunk_preset_id: 'general',
})
const uploadFile = ref(null)
const uploadTargetBaseId = ref(null)
const uploadErrorMessage = ref('')
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

const uploadTargetKnowledgeBase = computed(() =>
  knowledgeBases.value.find((item) => item.id === uploadTargetBaseId.value),
)

const selectedCreatePreset = computed(() =>
  chunkPresets.value.find((item) => item.value === createForm.value.chunk_preset_id),
)

const selectedKnowledgeBasePreset = computed(() =>
  chunkPresets.value.find((item) => item.value === selectedKnowledgeBase.value?.chunk_preset_id),
)

onMounted(() => {
  loadKnowledgeBases()
  loadChunkPresets()
})

async function loadChunkPresets() {
  try {
    chunkPresets.value = await listKnowledgeChunkPresets()
  } catch (error) {
    errorMessage.value = error.message
  }
}

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
  createForm.value = {
    name: '',
    description: '',
    chunk_preset_id: 'general',
  }
  submitMessage.value = ''
  errorMessage.value = ''
  createDialogOpen.value = true
}

function closeCreateDialog() {
  if (submitting.value) return
  createDialogOpen.value = false
}

function openUploadDialog() {
  if (!selectedKnowledgeBase.value) {
    errorMessage.value = '请先选择一个知识库。'
    return
  }
  uploadTargetBaseId.value = selectedKnowledgeBase.value.id
  uploadFile.value = null
  uploadErrorMessage.value = ''
  submitMessage.value = ''
  errorMessage.value = ''
  uploadDialogOpen.value = true
}

function closeUploadDialog() {
  if (submitting.value) return
  uploadDialogOpen.value = false
  uploadTargetBaseId.value = null
  uploadErrorMessage.value = ''
}

function handleFileChange(event) {
  uploadFile.value = event.target.files?.[0] || null
  uploadErrorMessage.value = ''
}

async function submitKnowledgeBase() {
  const name = createForm.value.name.trim()
  if (!name || submitting.value) return

  submitting.value = true
  submitMessage.value = '正在创建知识库...'
  errorMessage.value = ''

  try {
    const knowledgeBase = await createKnowledgeBase({
      name,
      description: createForm.value.description.trim(),
      user_key: selectionStore.userKey,
      chunk_preset_id: createForm.value.chunk_preset_id,
      chunk_parser_config: selectedCreatePreset.value?.default_config || {},
    })
    documentsByBaseId.value = {
      ...documentsByBaseId.value,
      [knowledgeBase.id]: [],
    }
    selectedBaseId.value = knowledgeBase.id
    await loadKnowledgeBases()
    selectedBaseId.value = knowledgeBase.id
    createDialogOpen.value = false
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    submitting.value = false
    submitMessage.value = ''
  }
}

async function submitKnowledgeDocument() {
  const knowledgeBaseId = uploadTargetBaseId.value
  if (!knowledgeBaseId || !uploadFile.value || submitting.value) return

  submitting.value = true
  submitMessage.value = '正在上传并解析文档...'
  uploadErrorMessage.value = ''
  errorMessage.value = ''

  try {
    await uploadKnowledgeDocument(knowledgeBaseId, selectionStore.userKey, uploadFile.value)
    await loadDocuments(knowledgeBaseId)
    selectedBaseId.value = knowledgeBaseId
    uploadDialogOpen.value = false
    uploadTargetBaseId.value = null
  } catch (error) {
    uploadErrorMessage.value = error.message
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
            <span v-if="selectedKnowledgeBase" class="chunk-preset-badge">
              分块策略：{{ selectedKnowledgeBasePreset?.label || selectedKnowledgeBase.chunk_preset_id || 'General' }}
            </span>
          </div>
          <button
            type="button"
            class="knowledge-create-button"
            :disabled="!selectedKnowledgeBase"
            @click="openUploadDialog"
          >
            <UploadCloud :size="16" />
            <span>添加文档</span>
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

    <div v-if="createDialogOpen" class="modal-backdrop" @click.self="closeCreateDialog">
      <section class="knowledge-upload-dialog" role="dialog" aria-modal="true" aria-labelledby="knowledge-upload-title">
        <header>
          <div>
            <h2 id="knowledge-upload-title">创建知识库</h2>
            <p>先创建知识库，再在知识库详情中添加和管理文档。</p>
          </div>
          <button type="button" class="dialog-close-button" :disabled="submitting" @click="closeCreateDialog">
            <X :size="18" />
          </button>
        </header>

        <form class="knowledge-upload-form" @submit.prevent="submitKnowledgeBase">
          <div class="knowledge-form-grid">
            <label>
              <span>知识库名称</span>
              <input v-model="createForm.name" type="text" maxlength="255" placeholder="例如：公司制度文档" required />
            </label>

            <label>
              <span>分块策略</span>
              <select v-model="createForm.chunk_preset_id">
                <option v-for="preset in chunkPresets" :key="preset.value" :value="preset.value">
                  {{ preset.label }}
                </option>
              </select>
            </label>
          </div>

          <p v-if="selectedCreatePreset" class="chunk-preset-description">
            {{ selectedCreatePreset.description }}
          </p>

          <label>
            <span>描述</span>
            <textarea v-model="createForm.description" rows="3" placeholder="记录知识库用途或文档范围" />
          </label>

          <p v-if="submitMessage" class="upload-status">
            <Loader2 class="spin" :size="16" />
            <span>{{ submitMessage }}</span>
          </p>

          <div class="dialog-actions">
            <button type="button" class="secondary-button" :disabled="submitting" @click="closeCreateDialog">
              取消
            </button>
            <button type="submit" class="knowledge-primary-button" :disabled="submitting || !createForm.name.trim()">
              <Loader2 v-if="submitting" class="spin" :size="16" />
              <Plus v-else :size="16" />
              <span>{{ submitting ? '创建中' : '创建知识库' }}</span>
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="uploadDialogOpen" class="modal-backdrop" @click.self="closeUploadDialog">
      <section class="knowledge-upload-dialog" role="dialog" aria-modal="true" aria-labelledby="document-upload-title">
        <header>
          <div>
            <h2 id="document-upload-title">添加文档</h2>
            <p>
              文档将添加到知识库“{{ uploadTargetKnowledgeBase?.name }}”，上传后会自动解析并建立索引。
            </p>
          </div>
          <button type="button" class="dialog-close-button" :disabled="submitting" @click="closeUploadDialog">
            <X :size="18" />
          </button>
        </header>

        <form class="knowledge-upload-form" @submit.prevent="submitKnowledgeDocument">
          <label class="file-drop-zone">
            <UploadCloud :size="28" />
            <strong>{{ uploadFile?.name || '选择要添加的文档' }}</strong>
            <span>{{ uploadFile ? formatFileSize(uploadFile.size) : '支持 md、txt、pdf、docx、xlsx、csv' }}</span>
            <input :accept="acceptedTypes" type="file" required @change="handleFileChange" />
          </label>

          <p v-if="submitMessage" class="upload-status">
            <Loader2 class="spin" :size="16" />
            <span>{{ submitMessage }}</span>
          </p>

          <p v-if="uploadErrorMessage" class="upload-error" role="alert">
            {{ uploadErrorMessage }}
          </p>

          <div class="dialog-actions">
            <button type="button" class="secondary-button" :disabled="submitting" @click="closeUploadDialog">
              取消
            </button>
            <button type="submit" class="knowledge-primary-button" :disabled="submitting || !uploadFile">
              <Loader2 v-if="submitting" class="spin" :size="16" />
              <UploadCloud v-else :size="16" />
              <span>{{ submitting ? '处理中' : '添加文档' }}</span>
            </button>
          </div>
        </form>
      </section>
    </div>
  </section>
</template>
