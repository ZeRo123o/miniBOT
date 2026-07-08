<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BarChart3, ClipboardList, FileText, Loader2, MoreVertical, Plus, Save, Search, Trash2, UploadCloud, X } from 'lucide-vue-next'
import {
  createKnowledgeBase,
  deleteEvaluationDataset,
  deleteEvaluationRun,
  deleteKnowledgeBase,
  deleteKnowledgeDocument,
  generateEvaluationDataset,
  getEvaluationDataset,
  getEvaluationRun,
  listKnowledgeChunkPresets,
  listKnowledgeBases,
  listKnowledgeDocuments,
  listEvaluationDatasets,
  listEvaluationRuns,
  getKnowledgeQueryParams,
  queryKnowledgeBase,
  runKnowledgeEvaluation,
  updateKnowledgeQueryParams,
  uploadEvaluationDataset,
  uploadKnowledgeDocument,
} from '../apis/resources'
import { listModels } from '../apis/modelProviders'
import { selectionStore } from '../stores/selectionStore'

const knowledgeTypes = ['全部类型', '文档知识库', '知识图谱']
const detailTabs = [
  { key: 'documents', label: '文档管理' },
  { key: 'query', label: '检索测试' },
  { key: 'evaluation', label: 'RAG评估' },
  { key: 'benchmark', label: '评估基准' },
]
const acceptedTypes = '.md,.markdown,.txt,.pdf,.docx,.xlsx,.csv'
const processingStatuses = new Set(['uploaded', 'parsing', 'chunking', 'embedding', 'indexing'])
const documentPollIntervalMs = 3000

const props = defineProps({
  active: {
    type: Boolean,
    default: true,
  },
})

const searchText = ref('')
const knowledgeBases = ref([])
const chunkPresets = ref([])
const documentsByBaseId = ref({})
const selectedBaseId = ref(null)
const activeDetailTab = ref('documents')
const loading = ref(false)
const errorMessage = ref('')
const queryText = ref('')
const queryLoading = ref(false)
const queryErrorMessage = ref('')
const queryResult = ref(null)
const queryConfigLoading = ref(false)
const queryConfigSaving = ref(false)
const queryConfigSnapshot = ref('')
const rerankModelsByProvider = ref({})
const rerankModelsLoading = ref(false)
const queryConfig = ref({
  search_mode: 'hybrid',
  final_top_k: 10,
  recall_top_k: 50,
  similarity_threshold: 0,
  bm25_top_k: 50,
  vector_weight: 0.7,
  bm25_weight: 0.3,
  bm25_drop_ratio_search: 0,
  use_reranker: false,
  reranker_model: '',
})
const evaluationDatasetsByBaseId = ref({})
const evaluationRunsByBaseId = ref({})
const evaluationLoading = ref(false)
const evaluationErrorMessage = ref('')
const evaluationResult = ref(null)
const selectedDatasetDetail = ref(null)
const selectedRunDetail = ref(null)
const datasetUploadDialogOpen = ref(false)
const datasetUploadFile = ref(null)
const benchmarkGenerating = ref(false)
const benchmarkGenerateDialogOpen = ref(false)
const chatModelsByProvider = ref({})
const chatModelsLoading = ref(false)
const embeddingModelsByProvider = ref({})
const embeddingModelsLoading = ref(false)
const datasetUploadForm = ref({
  name: '',
  description: '',
})
const benchmarkGenerateForm = ref({
  name: '',
  description: '',
  llm_model_spec: '',
  count: 10,
  candidate_chunk_count: 1,
})
const evaluationForm = ref({
  name: '',
  dataset_id: '',
  answer_llm_model_spec: '',
  judge_llm_model_spec: '',
})

const createDialogOpen = ref(false)
const uploadDialogOpen = ref(false)
const createForm = ref({
  name: '',
  description: '',
  kb_type: 'milvus',
  chunk_preset_id: 'general',
  embedding_model_spec: '',
  extraction_model_spec: '',
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

const queryResults = computed(() => queryResult.value?.results || [])

const rerankModelOptions = computed(() =>
  Object.values(rerankModelsByProvider.value).flatMap((group) =>
    (group.models || []).map((model) => ({
      ...model,
      provider_display_name: group.provider_display_name,
    })),
  ),
)

const chatModelOptions = computed(() =>
  Object.values(chatModelsByProvider.value).flatMap((group) =>
    (group.models || []).map((model) => ({
      ...model,
      provider_display_name: group.provider_display_name,
    })),
  ),
)

const embeddingModelOptions = computed(() =>
  Object.values(embeddingModelsByProvider.value).flatMap((group) =>
    (group.models || []).map((model) => ({
      ...model,
      provider_display_name: group.provider_display_name,
    })),
  ),
)

const createFormReady = computed(() => {
  if (!createForm.value.name.trim() || !createForm.value.embedding_model_spec) return false
  if (createForm.value.kb_type === 'lightrag' && !createForm.value.extraction_model_spec) return false
  return true
})

const selectedRerankerIsKnown = computed(() => {
  const selected = queryConfig.value.reranker_model
  return !selected || rerankModelOptions.value.some((model) => model.spec === selected)
})

const queryConfigDirty = computed(() => serializeQueryConfig(queryConfig.value) !== queryConfigSnapshot.value)

const selectedEvaluationDatasets = computed(() => evaluationDatasetsByBaseId.value[selectedBaseId.value] || [])

const selectedEvaluationRuns = computed(() => evaluationRunsByBaseId.value[selectedBaseId.value] || [])

const latestEvaluationRun = computed(() => selectedEvaluationRuns.value[0] || null)

const uploadTargetKnowledgeBase = computed(() =>
  knowledgeBases.value.find((item) => item.id === uploadTargetBaseId.value),
)

const selectedCreatePreset = computed(() =>
  chunkPresets.value.find((item) => item.value === createForm.value.chunk_preset_id),
)

const selectedKnowledgeBasePreset = computed(() =>
  chunkPresets.value.find((item) => item.value === selectedKnowledgeBase.value?.chunk_preset_id),
)

function normalizeQueryConfig(config) {
  return {
    ...config,
    reranker_model: config?.reranker_model || '',
  }
}

function buildQueryConfigPayload(config) {
  return {
    search_mode: config.search_mode,
    final_top_k: Number(config.final_top_k),
    recall_top_k: Number(config.recall_top_k),
    similarity_threshold: Number(config.similarity_threshold),
    bm25_top_k: Number(config.bm25_top_k),
    vector_weight: Number(config.vector_weight),
    bm25_weight: Number(config.bm25_weight),
    bm25_drop_ratio_search: Number(config.bm25_drop_ratio_search),
    use_reranker: Boolean(config.use_reranker),
    reranker_model: config.use_reranker ? config.reranker_model.trim() || null : null,
  }
}

function serializeQueryConfig(config) {
  return JSON.stringify(buildQueryConfigPayload(config))
}

onMounted(() => {
  loadKnowledgeBases()
  loadChunkPresets()
  loadRerankModels()
  loadChatModels()
  loadEmbeddingModels()
  if (props.active) startDocumentPolling()
})

onBeforeUnmount(() => {
  stopDocumentPolling()
})

watch(
  () => props.active,
  (active) => {
    if (active) {
      startDocumentPolling()
    } else {
      stopDocumentPolling()
    }
  },
)

watch(queryText, () => {
  if (queryLoading.value) return
  queryResult.value = null
  queryErrorMessage.value = ''
})

watch(
  () => createForm.value.kb_type,
  (kbType) => {
    if (!createForm.value.embedding_model_spec) {
      createForm.value.embedding_model_spec = embeddingModelOptions.value[0]?.spec || ''
    }
    if (kbType === 'lightrag' && !createForm.value.extraction_model_spec) {
      createForm.value.extraction_model_spec = chatModelOptions.value[0]?.spec || ''
    }
  },
)

watch(embeddingModelOptions, (options) => {
  if (!createForm.value.embedding_model_spec) {
    createForm.value.embedding_model_spec = options[0]?.spec || ''
  }
})

watch(chatModelOptions, (options) => {
  if (createForm.value.kb_type === 'lightrag' && !createForm.value.extraction_model_spec) {
    createForm.value.extraction_model_spec = options[0]?.spec || ''
  }
  if (!benchmarkGenerateForm.value.llm_model_spec) {
    benchmarkGenerateForm.value.llm_model_spec = options[0]?.spec || ''
  }
  for (const key of ['answer_llm_model_spec', 'judge_llm_model_spec']) {
    if (
      evaluationForm.value[key] &&
      !options.some((model) => model.spec === evaluationForm.value[key])
    ) {
      evaluationForm.value[key] = ''
    }
  }
})

function startDocumentPolling() {
  if (documentPollTimer) return
  documentPollTimer = window.setInterval(refreshProcessingDocuments, documentPollIntervalMs)
}

function stopDocumentPolling() {
  if (!documentPollTimer) return
  window.clearInterval(documentPollTimer)
  documentPollTimer = null
}

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
    knowledgeBases.value = await listKnowledgeBases(selectionStore.userId)
    if (!selectedBaseId.value && knowledgeBases.value.length) {
      selectedBaseId.value = knowledgeBases.value[0].id
      await loadDocuments(selectedBaseId.value)
      await loadQueryConfig(selectedBaseId.value)
      await loadEvaluationDatasets(selectedBaseId.value)
      await loadEvaluationRuns(selectedBaseId.value)
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
    [knowledgeBaseId]: await listKnowledgeDocuments(knowledgeBaseId, selectionStore.userId),
  }
}

async function loadRerankModels() {
  if (rerankModelsLoading.value) return
  rerankModelsLoading.value = true
  try {
    rerankModelsByProvider.value = await listModels('rerank')
  } catch (error) {
    queryErrorMessage.value = error.message
  } finally {
    rerankModelsLoading.value = false
  }
}

async function loadChatModels({ force = false } = {}) {
  if (chatModelsLoading.value) return
  if (!force && chatModelOptions.value.length) return
  chatModelsLoading.value = true
  try {
    chatModelsByProvider.value = await listModels('chat') || {}
    benchmarkGenerateForm.value.llm_model_spec = chatModelOptions.value[0]?.spec || ''
  } catch (error) {
    evaluationErrorMessage.value = error.message
  } finally {
    chatModelsLoading.value = false
  }
}

async function loadEmbeddingModels() {
  if (embeddingModelsLoading.value) return
  embeddingModelsLoading.value = true
  try {
    embeddingModelsByProvider.value = await listModels('embedding')
    if (!createForm.value.embedding_model_spec) {
      createForm.value.embedding_model_spec = embeddingModelOptions.value[0]?.spec || ''
    }
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    embeddingModelsLoading.value = false
  }
}

async function loadQueryConfig(knowledgeBaseId) {
  if (!knowledgeBaseId || queryConfigLoading.value) return
  queryConfigLoading.value = true
  try {
    const response = await getKnowledgeQueryParams(knowledgeBaseId, selectionStore.userId)
    queryConfig.value = {
      ...queryConfig.value,
      ...normalizeQueryConfig(response.data || {}),
    }
    queryConfigSnapshot.value = serializeQueryConfig(queryConfig.value)
  } catch (error) {
    queryErrorMessage.value = error.message
  } finally {
    queryConfigLoading.value = false
  }
}

async function loadEvaluationDatasets(knowledgeBaseId) {
  if (!knowledgeBaseId) return
  evaluationErrorMessage.value = ''
  try {
    const response = await listEvaluationDatasets(knowledgeBaseId, selectionStore.userId)
    evaluationDatasetsByBaseId.value = {
      ...evaluationDatasetsByBaseId.value,
      [knowledgeBaseId]: response.data || [],
    }
    if (!evaluationForm.value.dataset_id && response.data?.length) {
      evaluationForm.value.dataset_id = response.data[0].dataset_id
    }
  } catch (error) {
    evaluationErrorMessage.value = error.message
  }
}

async function loadEvaluationRuns(knowledgeBaseId) {
  if (!knowledgeBaseId) return
  evaluationErrorMessage.value = ''
  try {
    const response = await listEvaluationRuns(knowledgeBaseId, selectionStore.userId)
    evaluationRunsByBaseId.value = {
      ...evaluationRunsByBaseId.value,
      [knowledgeBaseId]: response.data || [],
    }
  } catch (error) {
    evaluationErrorMessage.value = error.message
  }
}

function openDatasetUploadDialog() {
  if (!selectedKnowledgeBase.value) return
  datasetUploadForm.value = {
    name: '',
    description: '',
  }
  datasetUploadFile.value = null
  evaluationErrorMessage.value = ''
  datasetUploadDialogOpen.value = true
}

function closeDatasetUploadDialog() {
  if (submitting.value) return
  datasetUploadDialogOpen.value = false
}

function handleDatasetFileChange(event) {
  datasetUploadFile.value = event.target.files?.[0] || null
  evaluationErrorMessage.value = ''
}

async function submitEvaluationDataset() {
  const knowledgeBase = selectedKnowledgeBase.value
  if (!knowledgeBase || !datasetUploadFile.value || submitting.value) return

  submitting.value = true
  submitMessage.value = '正在上传评估基准...'
  evaluationErrorMessage.value = ''
  try {
    await uploadEvaluationDataset(
      knowledgeBase.id,
      selectionStore.userId,
      datasetUploadFile.value,
      datasetUploadForm.value.name.trim() || datasetUploadFile.value.name,
      datasetUploadForm.value.description.trim(),
    )
    await loadEvaluationDatasets(knowledgeBase.id)
    datasetUploadDialogOpen.value = false
  } catch (error) {
    evaluationErrorMessage.value = error.message
  } finally {
    submitting.value = false
    submitMessage.value = ''
  }
}

function buildBenchmarkName() {
  const now = new Date()
  const date = now.toISOString().slice(0, 10)
  const suffix = Math.random().toString(36).slice(2, 6)
  return `Test-${date}-${suffix}`
}

async function openBenchmarkGenerateDialog() {
  if (!selectedKnowledgeBase.value) return
  evaluationErrorMessage.value = ''
  await loadChatModels({ force: !chatModelOptions.value.length })
  if (!benchmarkGenerateForm.value.name.trim()) {
    benchmarkGenerateForm.value.name = buildBenchmarkName()
  }
  if (!benchmarkGenerateForm.value.llm_model_spec) {
    benchmarkGenerateForm.value.llm_model_spec = chatModelOptions.value[0]?.spec || ''
  }
  benchmarkGenerateDialogOpen.value = true
}

function closeBenchmarkGenerateDialog() {
  if (benchmarkGenerating.value) return
  benchmarkGenerateDialogOpen.value = false
}

async function submitBenchmarkGeneration() {
  const knowledgeBase = selectedKnowledgeBase.value
  if (!knowledgeBase || benchmarkGenerating.value) return

  benchmarkGenerating.value = true
  evaluationErrorMessage.value = ''
  try {
    const response = await generateEvaluationDataset(knowledgeBase.id, {
      user_id: selectionStore.userId,
      name: benchmarkGenerateForm.value.name.trim(),
      description: benchmarkGenerateForm.value.description.trim(),
      llm_model_spec: benchmarkGenerateForm.value.llm_model_spec || null,
      count: Number(benchmarkGenerateForm.value.count),
      candidate_chunk_count: Number(benchmarkGenerateForm.value.candidate_chunk_count),
      concurrency_count: 4,
    })
    await loadEvaluationDatasets(knowledgeBase.id)
    if (response.data?.dataset_id) {
      evaluationForm.value.dataset_id = response.data.dataset_id
    }
    benchmarkGenerateDialogOpen.value = false
  } catch (error) {
    evaluationErrorMessage.value = error.message
  } finally {
    benchmarkGenerating.value = false
  }
}

async function showDatasetDetail(dataset) {
  if (!selectedKnowledgeBase.value || !dataset) return
  evaluationErrorMessage.value = ''
  try {
    const response = await getEvaluationDataset(selectedKnowledgeBase.value.id, dataset.dataset_id, selectionStore.userId)
    selectedDatasetDetail.value = response.data
  } catch (error) {
    evaluationErrorMessage.value = error.message
  }
}

function closeDatasetDetail() {
  selectedDatasetDetail.value = null
}

async function removeEvaluationDataset(dataset) {
  if (!dataset || deleting.value) return
  deleting.value = true
  evaluationErrorMessage.value = ''
  try {
    await deleteEvaluationDataset(dataset.dataset_id, selectionStore.userId)
    await loadEvaluationDatasets(selectedBaseId.value)
    if (evaluationForm.value.dataset_id === dataset.dataset_id) {
      evaluationForm.value.dataset_id = selectedEvaluationDatasets.value[0]?.dataset_id || ''
    }
  } catch (error) {
    evaluationErrorMessage.value = error.message
  } finally {
    deleting.value = false
  }
}

async function startEvaluation() {
  const knowledgeBase = selectedKnowledgeBase.value
  if (!knowledgeBase || !evaluationForm.value.dataset_id || evaluationLoading.value) return

  evaluationLoading.value = true
  evaluationResult.value = null
  evaluationErrorMessage.value = ''
  try {
    const response = await runKnowledgeEvaluation(knowledgeBase.id, {
      user_id: selectionStore.userId,
      dataset_id: evaluationForm.value.dataset_id,
      name: evaluationForm.value.name.trim() || null,
      model_config: {
        answer_llm_model_spec: evaluationForm.value.answer_llm_model_spec || null,
        judge_llm_model_spec: evaluationForm.value.judge_llm_model_spec || null,
      },
    })
    evaluationResult.value = response.data
    await loadEvaluationRuns(knowledgeBase.id)
  } catch (error) {
    evaluationErrorMessage.value = error.message
  } finally {
    evaluationLoading.value = false
  }
}

async function showRunDetail(run, errorOnly = false) {
  if (!selectedKnowledgeBase.value || !run) return
  evaluationErrorMessage.value = ''
  try {
    const response = await getEvaluationRun(selectedKnowledgeBase.value.id, run.run_id, selectionStore.userId, errorOnly)
    selectedRunDetail.value = response.data
  } catch (error) {
    evaluationErrorMessage.value = error.message
  }
}

function closeRunDetail() {
  selectedRunDetail.value = null
}

async function removeEvaluationRun(run) {
  if (!selectedKnowledgeBase.value || !run || deleting.value) return
  deleting.value = true
  evaluationErrorMessage.value = ''
  try {
    await deleteEvaluationRun(selectedKnowledgeBase.value.id, run.run_id, selectionStore.userId)
    await loadEvaluationRuns(selectedKnowledgeBase.value.id)
  } catch (error) {
    evaluationErrorMessage.value = error.message
  } finally {
    deleting.value = false
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
  queryResult.value = null
  queryErrorMessage.value = ''
  selectedBaseId.value = knowledgeBaseId
  if (!documentsByBaseId.value[knowledgeBaseId]) {
    await loadDocuments(knowledgeBaseId)
  }
  await loadQueryConfig(knowledgeBaseId)
  if (!evaluationDatasetsByBaseId.value[knowledgeBaseId]) {
    await loadEvaluationDatasets(knowledgeBaseId)
  }
  if (!evaluationRunsByBaseId.value[knowledgeBaseId]) {
    await loadEvaluationRuns(knowledgeBaseId)
  }
}

function selectDetailTab(tabKey) {
  activeDetailTab.value = tabKey
  openDocumentMenuId.value = null
  if ((tabKey === 'evaluation' || tabKey === 'benchmark') && !chatModelOptions.value.length) {
    loadChatModels({ force: true })
  }
  if (tabKey === 'evaluation' && selectedBaseId.value) {
    loadEvaluationRuns(selectedBaseId.value)
    loadEvaluationDatasets(selectedBaseId.value)
  }
  if (tabKey === 'benchmark' && selectedBaseId.value) {
    loadEvaluationDatasets(selectedBaseId.value)
  }
}

async function runQueryTest() {
  const knowledgeBase = selectedKnowledgeBase.value
  const query = queryText.value.trim()
  if (!knowledgeBase || !query || queryLoading.value) return

  queryLoading.value = true
  queryErrorMessage.value = ''
  try {
    queryResult.value = await queryKnowledgeBase(knowledgeBase.id, {
      user_id: selectionStore.userId,
      query,
      search_mode: queryConfig.value.search_mode,
      final_top_k: Number(queryConfig.value.final_top_k),
      recall_top_k: Number(queryConfig.value.recall_top_k),
      similarity_threshold: Number(queryConfig.value.similarity_threshold),
      bm25_top_k: Number(queryConfig.value.bm25_top_k),
      vector_weight: Number(queryConfig.value.vector_weight),
      bm25_weight: Number(queryConfig.value.bm25_weight),
      bm25_drop_ratio_search: Number(queryConfig.value.bm25_drop_ratio_search),
      include_distances: true,
      use_reranker: queryConfig.value.use_reranker,
      reranker_model: queryConfig.value.use_reranker ? queryConfig.value.reranker_model.trim() || null : null,
    })
  } catch (error) {
    queryErrorMessage.value = error.message
  } finally {
    queryLoading.value = false
  }
}

async function saveQueryConfig() {
  const knowledgeBase = selectedKnowledgeBase.value
  if (!knowledgeBase || queryConfigSaving.value || !queryConfigDirty.value) return

  queryConfigSaving.value = true
  queryErrorMessage.value = ''
  try {
    const configPayload = buildQueryConfigPayload(queryConfig.value)
    const response = await updateKnowledgeQueryParams(knowledgeBase.id, {
      user_id: selectionStore.userId,
      ...configPayload,
    })
    queryConfig.value = {
      ...queryConfig.value,
      ...normalizeQueryConfig(response.data || {}),
    }
    queryConfigSnapshot.value = serializeQueryConfig(queryConfig.value)
    await loadKnowledgeBases()
    selectedBaseId.value = knowledgeBase.id
  } catch (error) {
    queryErrorMessage.value = error.message
  } finally {
    queryConfigSaving.value = false
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
      await deleteKnowledgeBase(item.id, selectionStore.userId)
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
      await deleteKnowledgeDocument(item.id, selectionStore.userId)
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
    embedding_model_spec: embeddingModelOptions.value[0]?.spec || '',
    extraction_model_spec: chatModelOptions.value[0]?.spec || '',
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
      user_id: selectionStore.userId,
      kb_type: createForm.value.kb_type,
      chunk_preset_id: createForm.value.chunk_preset_id,
      chunk_parser_config: selectedCreatePreset.value?.default_config || {},
      embedding_model_spec: createForm.value.embedding_model_spec || null,
      extraction_model_spec:
        createForm.value.kb_type === 'lightrag' ? createForm.value.extraction_model_spec || null : null,
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
    await uploadKnowledgeDocument(knowledgeBaseId, selectionStore.userId, uploadFile.value)
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

function formatScore(score) {
  if (score === null || score === undefined || Number.isNaN(Number(score))) return '-'
  return Number(score).toFixed(4)
}

function formatPercent(score) {
  if (score === null || score === undefined || Number.isNaN(Number(score))) return '-'
  return `${(Number(score) * 100).toFixed(1)}%`
}

function metricValue(record, key) {
  return record?.metrics?.[key]
}

function truncateText(value, length = 120) {
  const text = String(value || '')
  return text.length > length ? `${text.slice(0, length)}...` : text
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

        <nav class="knowledge-detail-tabs" aria-label="知识库详情">
          <button
            v-for="tab in detailTabs"
            :key="tab.key"
            type="button"
            :class="{ active: activeDetailTab === tab.key }"
            @click="selectDetailTab(tab.key)"
          >
            <FileText v-if="tab.key === 'documents'" :size="16" />
            <Search v-else-if="tab.key === 'query'" :size="16" />
            <BarChart3 v-else-if="tab.key === 'evaluation'" :size="16" />
            <ClipboardList v-else :size="16" />
            <span>{{ tab.label }}</span>
          </button>
        </nav>

        <section v-if="activeDetailTab === 'documents'" class="knowledge-detail-panel">
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
        </section>

        <section v-else-if="activeDetailTab === 'query'" class="knowledge-query-layout">
          <div class="knowledge-query-main">
            <form class="knowledge-query-box" @submit.prevent="runQueryTest">
              <textarea
                v-model="queryText"
                rows="3"
                placeholder="输入检索问题"
                @keydown.enter.exact.prevent="runQueryTest"
              />
              <button type="submit" class="knowledge-query-submit" :disabled="queryLoading || !queryText.trim()">
                <Loader2 v-if="queryLoading" class="spin" :size="17" />
                <Search v-else :size="17" />
              </button>
            </form>

            <p v-if="queryErrorMessage" class="knowledge-inline-error">{{ queryErrorMessage }}</p>

            <div v-if="queryResult" class="knowledge-query-summary">
              <span>模式：{{ queryResult.search_mode }}</span>
              <span>召回：{{ queryResults.length }}</span>
            </div>

            <div v-if="queryResults.length" class="knowledge-query-results">
              <article v-for="(item, index) in queryResults" :key="item.metadata?.citation_id || index" class="knowledge-query-result">
                <header>
                  <strong>#{{ index + 1 }}</strong>
                  <span>Score {{ formatScore(item.score) }}</span>
                  <span v-if="item.rerank_score !== undefined">Rerank {{ formatScore(item.rerank_score) }}</span>
                </header>
                <p>{{ item.content }}</p>
                <footer>
                  <span>{{ item.metadata?.source || '未知来源' }}</span>
                  <span v-if="item.metadata?.chunk_index !== undefined">Chunk {{ item.metadata.chunk_index }}</span>
                  <span v-if="item.distance !== undefined">Distance {{ formatScore(item.distance) }}</span>
                </footer>
              </article>
            </div>
            <div v-else class="knowledge-document-empty">
              <Search :size="34" />
              <p>{{ queryResult ? '没有命中结果' : '输入问题后开始检索' }}</p>
            </div>
          </div>

          <aside class="knowledge-query-config">
            <header>
              <strong>检索配置</strong>
              <button
                type="button"
                class="knowledge-config-save"
                :disabled="queryConfigSaving || queryConfigLoading || !queryConfigDirty"
                @click="saveQueryConfig"
              >
                <Loader2 v-if="queryConfigSaving" class="spin" :size="15" />
                <Save v-else :size="15" />
                <span>{{ queryConfigSaving ? '保存中' : '保存' }}</span>
              </button>
            </header>

            <label>
              <span>检索模式</span>
              <select v-model="queryConfig.search_mode">
                <option value="hybrid">混合检索</option>
                <option value="vector">向量检索</option>
                <option value="keyword">关键词检索</option>
              </select>
            </label>

            <label>
              <span>最终返回 Chunk 数</span>
              <input v-model.number="queryConfig.final_top_k" type="number" min="1" max="100" />
            </label>

            <label>
              <span>召回 Chunk 数</span>
              <input v-model.number="queryConfig.recall_top_k" type="number" min="1" max="200" />
            </label>

            <label>
              <span>相似度阈值</span>
              <input v-model.number="queryConfig.similarity_threshold" type="number" min="0" max="1" step="0.05" />
            </label>

            <label>
              <span>BM25 召回数量</span>
              <input v-model.number="queryConfig.bm25_top_k" type="number" min="1" max="200" />
            </label>

            <label>
              <span>向量检索权重</span>
              <input v-model.number="queryConfig.vector_weight" type="number" min="0" step="0.1" />
            </label>

            <label>
              <span>BM25 权重</span>
              <input v-model.number="queryConfig.bm25_weight" type="number" min="0" step="0.1" />
            </label>

            <label>
              <span>BM25 稀疏项丢弃比例</span>
              <input v-model.number="queryConfig.bm25_drop_ratio_search" type="number" min="0" max="1" step="0.05" />
            </label>

            <label class="knowledge-config-switch">
              <input v-model="queryConfig.use_reranker" type="checkbox" />
              <span>启用重排序</span>
            </label>

            <label>
              <span>Rerank 模型</span>
              <select v-model="queryConfig.reranker_model" :disabled="!queryConfig.use_reranker || rerankModelsLoading">
                <option value="">默认配置</option>
                <option
                  v-if="queryConfig.reranker_model && !selectedRerankerIsKnown"
                  :value="queryConfig.reranker_model"
                >
                  {{ queryConfig.reranker_model }}（当前保存）
                </option>
                <option v-for="model in rerankModelOptions" :key="model.spec" :value="model.spec">
                  {{ model.provider_display_name }} / {{ model.display_name }}
                </option>
              </select>
            </label>
          </aside>
        </section>

        <section v-else-if="activeDetailTab === 'evaluation'" class="knowledge-evaluation-layout">
          <div class="knowledge-evaluation-main">
            <header class="knowledge-section-header">
              <div>
                <strong>RAG评估</strong>
                <span>使用当前知识库检索配置执行 Yuxi 风格 Recall/F1 和答案正确性评估。</span>
              </div>
              <button type="button" class="knowledge-primary-button" :disabled="evaluationLoading || !evaluationForm.dataset_id" @click="startEvaluation">
                <Loader2 v-if="evaluationLoading" class="spin" :size="16" />
                <BarChart3 v-else :size="16" />
                <span>{{ evaluationLoading ? '评估中' : '开始评估' }}</span>
              </button>
            </header>

            <p v-if="evaluationErrorMessage" class="knowledge-inline-error">{{ evaluationErrorMessage }}</p>

            <div class="knowledge-evaluation-form">
              <label>
                <span>评估名称</span>
                <input v-model="evaluationForm.name" type="text" placeholder="默认自动生成 eval-日期-编号" />
              </label>
              <label>
                <span>评估基准</span>
                <select v-model="evaluationForm.dataset_id">
                  <option value="">请选择评估基准</option>
                  <option v-for="dataset in selectedEvaluationDatasets" :key="dataset.dataset_id" :value="dataset.dataset_id">
                    {{ dataset.name }}（{{ dataset.item_count }}题）
                  </option>
                </select>
              </label>
              <label>
                <span>答案生成模型</span>
                <select v-model="evaluationForm.answer_llm_model_spec" :disabled="chatModelsLoading">
                  <option value="">不启用答案生成</option>
                  <option v-for="model in chatModelOptions" :key="`answer-${model.spec}`" :value="model.spec">
                    {{ model.provider_display_name }} / {{ model.display_name }}
                  </option>
                </select>
              </label>
              <label>
                <span>评判模型</span>
                <select v-model="evaluationForm.judge_llm_model_spec" :disabled="chatModelsLoading">
                  <option value="">不启用评判模型</option>
                  <option v-for="model in chatModelOptions" :key="`judge-${model.spec}`" :value="model.spec">
                    {{ model.provider_display_name }} / {{ model.display_name }}
                  </option>
                </select>
              </label>
            </div>

            <div class="knowledge-metric-grid">
              <div class="knowledge-metric">
                <span>Recall@10</span>
                <strong>{{ formatPercent(metricValue(latestEvaluationRun, 'recall@10')) }}</strong>
              </div>
              <div class="knowledge-metric">
                <span>F1@10</span>
                <strong>{{ formatPercent(metricValue(latestEvaluationRun, 'f1@10')) }}</strong>
              </div>
              <div class="knowledge-metric">
                <span>答案正确率</span>
                <strong>{{ formatPercent(metricValue(latestEvaluationRun, 'answer_correctness')) }}</strong>
              </div>
            </div>

            <div v-if="selectedEvaluationRuns.length" class="knowledge-evaluation-table">
              <div class="knowledge-evaluation-row header">
                <span>评估名称</span>
                <span>状态</span>
                <span>Recall@10</span>
                <span>题目</span>
                <span>操作</span>
              </div>
              <div v-for="run in selectedEvaluationRuns" :key="run.run_id" class="knowledge-evaluation-row">
                <span>{{ run.name }}</span>
                <span>{{ run.status }}</span>
                <span>{{ formatPercent(run.metrics?.['recall@10']) }}</span>
                <span>{{ run.completed_items }}/{{ run.total_items }}</span>
                <span class="knowledge-row-actions">
                  <button type="button" @click="showRunDetail(run)">详情</button>
                  <button type="button" @click="showRunDetail(run, true)">问题项</button>
                  <button type="button" @click="removeEvaluationRun(run)">删除</button>
                </span>
              </div>
            </div>
            <div v-else class="knowledge-document-empty">
              <BarChart3 :size="34" />
              <p>暂无评估记录，选择基准后开始评估。</p>
            </div>
          </div>
        </section>

        <section v-else class="knowledge-evaluation-layout">
          <div class="knowledge-evaluation-main">
            <header class="knowledge-section-header">
              <div>
                <strong>评估基准</strong>
                <span>上传 JSONL，每行包含 query，可选 gold_chunk_ids 和 gold_answer。</span>
              </div>
              <button type="button" class="knowledge-secondary-button" :disabled="benchmarkGenerating" @click="openBenchmarkGenerateDialog">
                <ClipboardList :size="18" />
                <span>自动生成</span>
                <span>{{ benchmarkGenerating ? '生成中' : '自动生成' }}</span>
              </button>
              <button type="button" class="knowledge-primary-button" @click="openDatasetUploadDialog">
                <UploadCloud :size="18" />
                <span>上传基准</span>
                <span>上传基准</span>
              </button>
            </header>

            <p v-if="evaluationErrorMessage" class="knowledge-inline-error">{{ evaluationErrorMessage }}</p>

            <div v-if="selectedEvaluationDatasets.length" class="knowledge-evaluation-table">
              <div class="knowledge-evaluation-row header benchmark">
                <span>名称</span>
                <span>题目数</span>
                <span>Gold Chunk</span>
                <span>标准答案</span>
                <span>操作</span>
              </div>
              <div v-for="dataset in selectedEvaluationDatasets" :key="dataset.dataset_id" class="knowledge-evaluation-row benchmark">
                <span>{{ dataset.name }}</span>
                <span>{{ dataset.item_count }}</span>
                <span>{{ dataset.has_gold_chunks ? '有' : '无' }}</span>
                <span>{{ dataset.has_gold_answers ? '有' : '无' }}</span>
                <span class="knowledge-row-actions">
                  <button type="button" @click="showDatasetDetail(dataset)">预览</button>
                  <button type="button" @click="removeEvaluationDataset(dataset)">删除</button>
                </span>
              </div>
            </div>
            <div v-else class="knowledge-document-empty">
              <ClipboardList :size="34" />
              <p>暂无评估基准，先上传 JSONL 文件。</p>
            </div>
          </div>
        </section>
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
              <span>Embedding 模型</span>
              <select v-model="createForm.embedding_model_spec" :disabled="embeddingModelsLoading">
                <option value="">{{ embeddingModelsLoading ? '加载中...' : '请选择 Embedding 模型' }}</option>
                <option v-for="model in embeddingModelOptions" :key="model.spec" :value="model.spec">
                  {{ model.provider_display_name }} / {{ model.display_name }}
                </option>
              </select>
            </label>

            <label v-if="createForm.kb_type === 'lightrag'">
              <span>知识抽取模型</span>
              <select v-model="createForm.extraction_model_spec" :disabled="chatModelsLoading">
                <option value="">{{ chatModelsLoading ? '加载中...' : '请选择知识抽取模型' }}</option>
                <option v-for="model in chatModelOptions" :key="`extract-${model.spec}`" :value="model.spec">
                  {{ model.provider_display_name }} / {{ model.display_name }}
                </option>
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
            <button type="submit" class="knowledge-primary-button" :disabled="submitting || !createFormReady">
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

    <div v-if="benchmarkGenerateDialogOpen" class="modal-backdrop" @click.self="closeBenchmarkGenerateDialog">
      <section class="benchmark-generate-dialog" role="dialog" aria-modal="true" aria-labelledby="benchmark-generate-title">
        <header>
          <div>
            <h2 id="benchmark-generate-title">自动生成评估基准</h2>
          </div>
          <button type="button" class="dialog-close-button" :disabled="benchmarkGenerating" @click="closeBenchmarkGenerateDialog">
            <X :size="18" />
          </button>
        </header>

        <form class="benchmark-generate-form" @submit.prevent="submitBenchmarkGeneration">
          <label>
            <span><b>*</b> 基准名称</span>
            <input v-model="benchmarkGenerateForm.name" type="text" required maxlength="255" />
          </label>

          <label>
            <span>描述</span>
            <textarea v-model="benchmarkGenerateForm.description" rows="3" placeholder="请输入评估基准描述（可选）" />
          </label>

          <div class="benchmark-build-mode">
            <span>构建方式</span>
            <div class="benchmark-mode-grid">
              <article class="benchmark-mode-card active">
                <strong>向量构建</strong>
                <small>基于向量相似度召回 chunks，稳定适用于所有知识库。</small>
              </article>
              <article class="benchmark-mode-card disabled">
                <strong>图增强构建</strong>
                <small>当前知识库尚未完成图谱构建，暂不能使用图增强构建。</small>
              </article>
            </div>
          </div>

          <label>
            <span><b>*</b> LLM模型配置</span>
            <select v-model="benchmarkGenerateForm.llm_model_spec" required :disabled="chatModelsLoading">
              <option value="">请选择模型</option>
              <option v-for="model in chatModelOptions" :key="model.spec" :value="model.spec">
                {{ model.provider_display_name }} / {{ model.display_name }}
              </option>
            </select>
          </label>

          <div class="benchmark-param-grid">
            <label>
              <span><b>*</b> 问题数量</span>
              <input v-model.number="benchmarkGenerateForm.count" type="number" min="1" max="100" required />
            </label>
            <label>
              <span>候选 Chunk 数量</span>
              <input v-model.number="benchmarkGenerateForm.candidate_chunk_count" type="number" min="0" max="7" />
            </label>
          </div>

          <p v-if="evaluationErrorMessage" class="upload-error">{{ evaluationErrorMessage }}</p>

          <div class="dialog-actions">
            <button type="button" class="secondary-button" :disabled="benchmarkGenerating" @click="closeBenchmarkGenerateDialog">
              取消
            </button>
            <button type="submit" class="knowledge-primary-button" :disabled="benchmarkGenerating || !benchmarkGenerateForm.name.trim() || !benchmarkGenerateForm.llm_model_spec">
              <Loader2 v-if="benchmarkGenerating" class="spin" :size="16" />
              <span>{{ benchmarkGenerating ? '生成中' : '确定' }}</span>
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="datasetUploadDialogOpen" class="modal-backdrop" @click.self="closeDatasetUploadDialog">
      <section class="knowledge-upload-dialog" role="dialog" aria-modal="true" aria-labelledby="dataset-upload-title">
        <header>
          <div>
            <h2 id="dataset-upload-title">上传评估基准</h2>
            <p>JSONL 每行一个样本：query 必填，gold_chunk_ids 和 gold_answer 可选。</p>
          </div>
          <button type="button" class="dialog-close-button" :disabled="submitting" @click="closeDatasetUploadDialog">
            <X :size="18" />
          </button>
        </header>

        <form class="knowledge-upload-form" @submit.prevent="submitEvaluationDataset">
          <div class="knowledge-form-grid">
            <label>
              <span>基准名称</span>
              <input v-model="datasetUploadForm.name" type="text" placeholder="默认使用文件名" />
            </label>
            <label>
              <span>描述</span>
              <input v-model="datasetUploadForm.description" type="text" placeholder="例如：制度问答回归集" />
            </label>
          </div>

          <label class="file-drop-zone">
            <UploadCloud :size="28" />
            <strong>{{ datasetUploadFile?.name || '选择 JSONL 评估基准' }}</strong>
            <span>{{ datasetUploadFile ? formatFileSize(datasetUploadFile.size) : '每行包含 query、gold_chunk_ids、gold_answer' }}</span>
            <input accept=".jsonl,application/x-ndjson,application/jsonl" type="file" required @change="handleDatasetFileChange" />
          </label>

          <p v-if="submitMessage" class="upload-status">
            <Loader2 class="spin" :size="16" />
            <span>{{ submitMessage }}</span>
          </p>
          <p v-if="evaluationErrorMessage" class="upload-error">{{ evaluationErrorMessage }}</p>

          <div class="dialog-actions">
            <button type="button" class="secondary-button" :disabled="submitting" @click="closeDatasetUploadDialog">
              取消
            </button>
            <button type="submit" class="knowledge-primary-button" :disabled="submitting || !datasetUploadFile">
              <Loader2 v-if="submitting" class="spin" :size="16" />
              <UploadCloud v-else :size="16" />
              <span>{{ submitting ? '上传中' : '上传基准' }}</span>
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="selectedDatasetDetail" class="modal-backdrop" @click.self="closeDatasetDetail">
      <section class="knowledge-detail-dialog" role="dialog" aria-modal="true">
        <header>
          <div>
            <h2>{{ selectedDatasetDetail.name }}</h2>
            <p>{{ selectedDatasetDetail.item_count }} 个问题 · Gold Chunk {{ selectedDatasetDetail.has_gold_chunks ? '可用' : '缺失' }} · 标准答案 {{ selectedDatasetDetail.has_gold_answers ? '可用' : '缺失' }}</p>
          </div>
          <button type="button" class="dialog-close-button" @click="closeDatasetDetail">
            <X :size="18" />
          </button>
        </header>
        <div class="knowledge-detail-list">
          <article v-for="item in selectedDatasetDetail.items" :key="item.item_id" class="knowledge-detail-item">
            <strong>{{ item.query }}</strong>
            <p v-if="item.gold_answer">标准答案：{{ truncateText(item.gold_answer, 180) }}</p>
            <span>Gold Chunk：{{ item.gold_chunk_ids?.join(', ') || '-' }}</span>
          </article>
        </div>
      </section>
    </div>

    <div v-if="selectedRunDetail" class="modal-backdrop" @click.self="closeRunDetail">
      <section class="knowledge-detail-dialog wide" role="dialog" aria-modal="true">
        <header>
          <div>
            <h2>评估结果 - {{ selectedRunDetail.name }}</h2>
            <p>
              {{ selectedRunDetail.status }} · {{ selectedRunDetail.completed_items }}/{{ selectedRunDetail.total_items }}
              · Overall {{ formatPercent(selectedRunDetail.overall_score) }}
            </p>
          </div>
          <button type="button" class="dialog-close-button" @click="closeRunDetail">
            <X :size="18" />
          </button>
        </header>

        <div class="knowledge-metric-grid compact">
          <div v-for="(value, key) in selectedRunDetail.metrics" :key="key" class="knowledge-metric">
            <span>{{ key }}</span>
            <strong>{{ typeof value === 'number' ? formatPercent(value) : value }}</strong>
          </div>
        </div>

        <div class="knowledge-detail-list">
          <article v-for="(item, index) in selectedRunDetail.items" :key="`${item.query}-${index}`" class="knowledge-detail-item">
            <header>
              <strong>{{ item.query }}</strong>
              <span>Recall@10 {{ formatPercent(item.metrics?.['recall@10']) }}</span>
            </header>
            <p v-if="item.generated_answer">生成答案：{{ truncateText(item.generated_answer, 220) }}</p>
            <p v-if="item.gold_answer">标准答案：{{ truncateText(item.gold_answer, 220) }}</p>
            <span>Gold Chunk：{{ item.gold_chunk_ids?.join(', ') || '-' }}</span>
            <span>命中 Chunk：{{ item.retrieved_chunks?.map((chunk) => chunk.metadata?.chunk_id).filter(Boolean).slice(0, 10).join(', ') || '-' }}</span>
          </article>
        </div>
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
