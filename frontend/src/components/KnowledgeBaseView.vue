<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { FileText, Loader2, MoreVertical, Plus, Search, Trash2, UploadCloud, X } from 'lucide-vue-next'
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeDocument,
  listKnowledgeChunkPresets,
  listKnowledgeBases,
  listKnowledgeDocuments,
  uploadKnowledgeDocument,
} from '../apis/resources'
import { selectionStore } from '../stores/selectionStore'

const knowledgeTypes = ['全部类型', '文档知识库', '知识图谱']
const acceptedTypes = '.md,.markdown,.txt,.pdf,.docx,.xlsx,.csv'
const processingStatuses = new Set(['uploaded', 'parsing', 'chunking', 'embedding', 'indexing'])
const documentPollIntervalMs = 3000

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
  kb_type: 'milvus',
  chunk_preset_id: 'general',
})
const uploadFile = ref(null)
const uploadTargetBaseId = ref(null)
const uploadErrorMessage = ref('')
const submitting = ref(false)
const submitMessage = ref('')
const deleting = ref(false)
const deleteTarget = ref(null)
const openDocumentMenuId = ref(null)
let documentPollTimer = null
let documentRefreshPending = false

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
  documentPollTimer = window.setInterval(refreshProcessingDocuments, documentPollIntervalMs)
})

onBeforeUnmount(() => {
  if (documentPollTimer) {
    window.clearInterval(documentPollTimer)
  }
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

async function refreshProcessingDocuments() {
  const knowledgeBaseId = selectedBaseId.value
  if (!knowledgeBaseId || documentRefreshPending) return

  const documents = documentsByBaseId.value[knowledgeBaseId] || []
  if (!documents.some((document) => processingStatuses.has(document.status))) return

  documentRefreshPending = true
  try {
    await loadDocuments(knowledgeBaseId)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    documentRefreshPending = false
  }
}

async function selectKnowledgeBase(knowledgeBaseId) {
  openDocumentMenuId.value = null
  selectedBaseId.value = knowledgeBaseId
  if (!documentsByBaseId.value[knowledgeBaseId]) {
    await loadDocuments(knowledgeBaseId)
  }
}

function requestDeleteKnowledgeBase(knowledgeBase) {
  errorMessage.value = ''
  deleteTarget.value = { kind: 'knowledgeBase', item: knowledgeBase }
}

function toggleDocumentMenu(documentId) {
  openDocumentMenuId.value = openDocumentMenuId.value === documentId ? null : documentId
}

function requestDeleteDocument(document) {
  openDocumentMenuId.value = null
  errorMessage.value = ''
  deleteTarget.value = { kind: 'document', item: document }
}

function closeDeleteDialog() {
  if (deleting.value) return
  deleteTarget.value = null
}

async function confirmDelete() {
  if (!deleteTarget.value || deleting.value) return

  deleting.value = true
  errorMessage.value = ''
  const { kind, item } = deleteTarget.value
  try {
    if (kind === 'knowledgeBase') {
      const deletedIndex = knowledgeBases.value.findIndex((knowledgeBase) => knowledgeBase.id === item.id)
      await deleteKnowledgeBase(item.id, selectionStore.userKey)
      knowledgeBases.value = knowledgeBases.value.filter((knowledgeBase) => knowledgeBase.id !== item.id)
      const nextDocuments = { ...documentsByBaseId.value }
      delete nextDocuments[item.id]
      documentsByBaseId.value = nextDocuments
      selectionStore.resources.knowledgeBase = selectionStore.resources.knowledgeBase.filter(
        (knowledgeBase) => knowledgeBase.id !== item.id,
      )
      selectionStore.selection.knowledge_base_ids = selectionStore.selection.knowledge_base_ids.filter(
        (knowledgeBaseId) => knowledgeBaseId !== item.id,
      )

      const nextKnowledgeBase = knowledgeBases.value[deletedIndex] || knowledgeBases.value[deletedIndex - 1]
      selectedBaseId.value = nextKnowledgeBase?.id || null
      if (nextKnowledgeBase && !documentsByBaseId.value[nextKnowledgeBase.id]) {
        await loadDocuments(nextKnowledgeBase.id)
      }
    } else {
      await deleteKnowledgeDocument(item.id, selectionStore.userKey)
      await loadDocuments(item.knowledge_base_id)
    }
    deleteTarget.value = null
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    deleting.value = false
  }
}

function openCreateDialog() {
  createForm.value = {
    name: '',
    description: '',
    kb_type: 'milvus',
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
      kb_type: createForm.value.kb_type,
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
    indexing: '图谱构建中',
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
        <div
          v-for="item in filteredKnowledgeBases"
          :key="item.id"
          class="knowledge-card"
          :class="{ active: item.id === selectedBaseId }"
        >
          <button
            type="button"
            class="knowledge-card-select"
            @click="selectKnowledgeBase(item.id)"
          >
            <strong>{{ item.name }}</strong>
            <span>{{ item.description || '暂无描述' }}</span>
            <span>{{ item.kb_type === 'lightrag' ? 'LightRAG 图知识库' : 'Milvus 文档知识库' }}</span>
          </button>
          <button
            type="button"
            class="knowledge-delete-button"
            :aria-label="`删除知识库 ${item.name}`"
            :title="`删除知识库 ${item.name}`"
            @click.stop="requestDeleteKnowledgeBase(item)"
          >
            <Trash2 :size="17" />
          </button>
        </div>
      </aside>

      <main class="knowledge-detail">
        <div class="knowledge-detail-header">
          <div>
            <h2>{{ selectedKnowledgeBase?.name || '请选择知识库' }}</h2>
            <p>{{ selectedKnowledgeBase?.description || '上传文档后会自动转为 Markdown 并保存解析状态。' }}</p>
            <span v-if="selectedKnowledgeBase" class="chunk-preset-badge">
              {{ selectedKnowledgeBase.kb_type === 'lightrag' ? 'LightRAG' : 'Milvus' }}
              · 分块策略：{{ selectedKnowledgeBasePreset?.label || selectedKnowledgeBase.chunk_preset_id || 'General' }}
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
            <div class="knowledge-document-info">
              <strong>{{ document.filename }}</strong>
              <span>{{ formatFileSize(document.file_size) }}</span>
            </div>
            <em :class="['document-status', document.status]">{{ statusText(document.status) }}</em>
            <div class="document-actions">
              <button
                type="button"
                class="document-menu-button"
                :aria-label="`管理文档 ${document.filename}`"
                @click.stop="toggleDocumentMenu(document.id)"
              >
                <MoreVertical :size="18" />
              </button>
              <div v-if="openDocumentMenuId === document.id" class="document-action-menu">
                <button type="button" @click="requestDeleteDocument(document)">
                  <Trash2 :size="15" />
                  <span>删除文档</span>
                </button>
              </div>
            </div>
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
              <span>知识库类型</span>
              <select v-model="createForm.kb_type">
                <option value="milvus">Milvus 文档知识库</option>
                <option value="lightrag">LightRAG 图知识库</option>
              </select>
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

    <div v-if="deleteTarget" class="modal-backdrop" @click.self="closeDeleteDialog">
      <section class="knowledge-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-confirm-title">
        <header>
          <div class="delete-dialog-icon">
            <Trash2 :size="22" />
          </div>
          <div>
            <h2 id="delete-confirm-title">
              {{ deleteTarget.kind === 'knowledgeBase' ? '删除知识库' : '删除文档' }}
            </h2>
            <p v-if="deleteTarget.kind === 'knowledgeBase'">
              确定删除知识库“{{ deleteTarget.item.name }}”吗？其中的文档、分块、向量索引、图谱数据和存储文件都会被永久删除。
            </p>
            <p v-else>
              确定删除文档“{{ deleteTarget.item.filename }}”吗？对应的分块、向量或图谱索引以及存储文件都会被永久删除。
            </p>
          </div>
        </header>
        <p class="delete-dialog-warning">此操作不可恢复。正在处理中的内容禁止删除。</p>
        <div class="dialog-actions">
          <button type="button" class="secondary-button" :disabled="deleting" @click="closeDeleteDialog">
            取消
          </button>
          <button type="button" class="danger-button" :disabled="deleting" @click="confirmDelete">
            <Loader2 v-if="deleting" class="spin" :size="16" />
            <Trash2 v-else :size="16" />
            <span>{{ deleting ? '删除中' : '确认删除' }}</span>
          </button>
        </div>
      </section>
    </div>
  </section>
</template>
