<script setup>
import {
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CloudDownload,
  X,
  Eye,
  EyeOff,
  FlaskConical,
  Home,
  KeyRound,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  createModelProvider,
  deleteModelProvider,
  fetchRemoteModels,
  refreshModelCache,
  testModelProviderCredentials,
  testProviderModel,
  updateModelProvider,
  updateModelUse,
} from '../apis/modelProviders'
import {
  loadModelProviderWorkspace,
  modelProviderStore,
} from '../stores/modelProviderStore'
import AppSelect from './AppSelect.vue'
import ProviderIcon from './ProviderIcon.vue'

const RUNTIME_USES = [{ key: 'deep_research_model' }]
const providerTypeOptions = ['openai', 'anthropic', 'gemini', 'openrouter'].map((value) => ({
  value,
  label: value,
}))
const modelTypeOptions = ['chat', 'embedding', 'rerank'].map((value) => ({
  value,
  label: value,
}))

const providers = computed(() => modelProviderStore.providers)
const modelUses = computed(() => modelProviderStore.modelUses)
const chatModelsByProvider = computed(() => modelProviderStore.chatModelsByProvider)
const loading = computed(() => modelProviderStore.loading)

const activeProviderId = ref('')
const screenMode = ref('list')
const keyword = ref('')
const statusFilter = ref('all')
const typeFilter = ref('all')
const saving = ref(false)
const testingSpec = ref('')
const remoteLoading = ref(false)
const remoteModalOpen = ref(false)
const remoteKeyword = ref('')
const remoteTypeFilter = ref('all')
const showApiKey = ref(false)
const statusMessage = ref('')
const errorMessage = ref('')
const lastTestResult = ref(null)
const credentialTesting = ref(false)
const credentialTestResult = ref(null)
const credentialTestSignature = ref('')
const modelTestResults = reactive({})
const remoteModels = ref([])
const modelPageRef = ref(null)
const modelToasts = ref([])
const modelPage = ref(1)
const modelPageSize = ref(10)
const modelPageSizeOptions = [10, 20, 50].map((value) => ({
  value,
  label: `${value} 条/页`,
}))
let statusMessageTimer = null
let errorMessageTimer = null
let nextToastId = 0
const toastTimers = new Map()

function enqueueModelToast(message, type, duration) {
  const id = ++nextToastId
  modelToasts.value.push({ id, message, type })
  const timer = window.setTimeout(() => {
    modelToasts.value = modelToasts.value.filter((toast) => toast.id !== id)
    toastTimers.delete(id)
  }, duration)
  toastTimers.set(id, timer)
}

watch(statusMessage, (message) => {
  window.clearTimeout(statusMessageTimer)
  if (message) {
    enqueueModelToast(message, 'success', 2000)
    statusMessageTimer = window.setTimeout(() => {
      statusMessage.value = ''
    }, 2000)
  }
})

watch(errorMessage, (message) => {
  window.clearTimeout(errorMessageTimer)
  if (message) {
    enqueueModelToast(message, 'error', 3000)
    errorMessageTimer = window.setTimeout(() => {
      errorMessage.value = ''
    }, 3000)
  }
})

const providerForm = reactive({
  provider_id: '',
  display_name: '',
  provider_type: 'openai',
  default_protocol: 'openai_compatible',
  base_url: '',
  embedding_base_url: '',
  rerank_base_url: '',
  models_endpoint: '/models',
  embedding_models_endpoint: '',
  rerank_models_endpoint: '',
  api_key_env: '',
  api_key: '',
  capabilitiesText: 'chat',
  headersText: '{}',
  extraText: '{}',
  is_enabled: true,
})

const modelForm = reactive({
  id: '',
  type: 'chat',
  dimension: '',
})

const activeProvider = computed(() =>
  providers.value.find((provider) => provider.provider_id === activeProviderId.value),
)

const providerFormModels = computed(() => activeProvider.value?.enabled_models || [])

const currentCredentialSignature = computed(() => JSON.stringify({
  base_url: providerForm.base_url.trim(),
  models_endpoint: providerForm.models_endpoint.trim(),
  api_key_env: providerForm.api_key_env.trim(),
  api_key: providerForm.api_key,
  headers: providerForm.headersText,
}))

const credentialTestState = computed(() => {
  if (credentialTesting.value) return 'testing'
  if (!credentialTestResult.value) return 'idle'
  if (credentialTestSignature.value !== currentCredentialSignature.value) return 'stale'
  return credentialTestResult.value.status === 'available' ? 'success' : 'error'
})

const modelPageCount = computed(() =>
  Math.max(1, Math.ceil(providerFormModels.value.length / modelPageSize.value)),
)

const paginatedProviderModels = computed(() => {
  const start = (modelPage.value - 1) * modelPageSize.value
  return providerFormModels.value.slice(start, start + modelPageSize.value)
})

// 页数较多时仅展示当前页附近的五个页码，避免分页栏挤压模型表格。
const visibleModelPages = computed(() => {
  const total = modelPageCount.value
  if (total <= 5) return Array.from({ length: total }, (_, index) => index + 1)
  const start = Math.min(Math.max(modelPage.value - 2, 1), total - 4)
  return Array.from({ length: 5 }, (_, index) => start + index)
})

watch(activeProviderId, () => {
  modelPage.value = 1
})

watch(modelPageSize, () => {
  modelPage.value = 1
})

watch(
  () => providerFormModels.value.length,
  () => {
    // 删除当前页最后一项后自动退回有效页，避免出现空白页面。
    modelPage.value = Math.min(modelPage.value, modelPageCount.value)
  },
)

const filteredRemoteModels = computed(() => {
  const query = remoteKeyword.value.trim().toLowerCase()
  return remoteModels.value.filter((model) => {
    const modelType = model.type || 'chat'
    const matchesType = remoteTypeFilter.value === 'all' || modelType === remoteTypeFilter.value
    const matchesKeyword =
      !query ||
      [model.id, model.display_name, model.name].some((value) =>
        String(value || '').toLowerCase().includes(query),
      )
    return matchesType && matchesKeyword
  })
})

const chatModelOptions = computed(() =>
  Object.values(chatModelsByProvider.value).flatMap((group) =>
    (group.models || []).map((model) => ({
      ...model,
      provider_display_name: group.provider_display_name,
    })),
  ),
)

const runtimeModelOptions = computed(() => [
  { value: '', label: '未选择' },
  ...chatModelOptions.value.map((model) => ({
    value: model.spec,
    label: `${model.provider_display_name} / ${model.display_name}`,
  })),
])

const filteredProviders = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return providers.value
    .filter((provider) => {
      const matchesKeyword =
        !query ||
        [provider.provider_id, provider.display_name, provider.base_url].some((value) =>
          String(value || '').toLowerCase().includes(query),
        )
      const matchesStatus =
        statusFilter.value === 'all' ||
        (statusFilter.value === 'enabled' && provider.is_enabled) ||
        (statusFilter.value === 'disabled' && !provider.is_enabled)
      const matchesType =
        typeFilter.value === 'all' ||
        (provider.enabled_models || []).some((model) => model.type === typeFilter.value)
      return matchesKeyword && matchesStatus && matchesType
    })
    .sort((a, b) => Number(b.is_enabled) - Number(a.is_enabled) || a.provider_id.localeCompare(b.provider_id))
})

function providerModelCount(provider, type) {
  return (provider.enabled_models || []).filter((model) => model.type === type).length
}

function isModelEnabled(model) {
  const modelType = model.type || 'chat'
  return providerFormModels.value.some((item) => item.id === model.id && item.type === modelType)
}

function providerToggleLabel(provider) {
  return provider?.is_enabled ? '停用' : '启用'
}

function modelUseSpec(modelUse) {
  return modelUses.value.find((item) => item.model_use === modelUse)?.model_spec || ''
}

function modelLabel(spec) {
  if (!spec) return '未选择'
  const option = chatModelOptions.value.find((model) => model.spec === spec)
  return option ? `${option.provider_display_name} / ${option.display_name}` : spec
}

function parseJson(text, label) {
  try {
    const value = JSON.parse(text || '{}')
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error()
    return value
  } catch {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
}

function splitCapabilities(text) {
  return text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function fillProviderForm(provider) {
  if (!provider) return
  activeProviderId.value = provider.provider_id
  Object.assign(providerForm, {
    provider_id: provider.provider_id,
    display_name: provider.display_name,
    provider_type: provider.provider_type || 'openai',
    default_protocol: provider.default_protocol || 'openai_compatible',
    base_url: provider.base_url || '',
    embedding_base_url: provider.embedding_base_url || '',
    rerank_base_url: provider.rerank_base_url || '',
    models_endpoint: provider.models_endpoint || '',
    embedding_models_endpoint: provider.embedding_models_endpoint || '',
    rerank_models_endpoint: provider.rerank_models_endpoint || '',
    api_key_env: provider.api_key_env || '',
    api_key: '',
    capabilitiesText: (provider.capabilities || ['chat']).join(', '),
    headersText: JSON.stringify(provider.headers_json || {}, null, 2),
    extraText: JSON.stringify(provider.extra_json || {}, null, 2),
    is_enabled: provider.is_enabled,
  })
  lastTestResult.value = null
  credentialTestResult.value = null
  credentialTestSignature.value = ''
}

function resetProviderForm() {
  activeProviderId.value = ''
  Object.assign(providerForm, {
    provider_id: '',
    display_name: '',
    provider_type: 'openai',
    default_protocol: 'openai_compatible',
    base_url: '',
    embedding_base_url: '',
    rerank_base_url: '',
    models_endpoint: '/models',
    embedding_models_endpoint: '',
    rerank_models_endpoint: '',
    api_key_env: '',
    api_key: '',
    capabilitiesText: 'chat',
    headersText: '{}',
    extraText: '{}',
    is_enabled: true,
  })
  Object.assign(modelForm, { id: '', type: 'chat', dimension: '' })
  lastTestResult.value = null
  credentialTestResult.value = null
  credentialTestSignature.value = ''
  remoteModels.value = []
}

function openProviderDetail(provider) {
  fillProviderForm(provider)
  screenMode.value = 'detail'
}

function openNewProvider() {
  resetProviderForm()
  screenMode.value = 'detail'
}

function backToList() {
  screenMode.value = 'list'
  errorMessage.value = ''
}

function buildProviderPayload() {
  const payload = {
    display_name: providerForm.display_name,
    provider_type: providerForm.provider_type,
    default_protocol: providerForm.default_protocol || null,
    base_url: providerForm.base_url,
    embedding_base_url: providerForm.embedding_base_url || null,
    rerank_base_url: providerForm.rerank_base_url || null,
    models_endpoint: providerForm.models_endpoint || null,
    embedding_models_endpoint: providerForm.embedding_models_endpoint || null,
    rerank_models_endpoint: providerForm.rerank_models_endpoint || null,
    api_key_env: providerForm.api_key_env || null,
    capabilities: splitCapabilities(providerForm.capabilitiesText),
    headers_json: parseJson(providerForm.headersText, 'Headers JSON'),
    extra_json: parseJson(providerForm.extraText, 'Extra JSON'),
    is_enabled: providerForm.is_enabled,
  }
  if (!activeProviderId.value) payload.provider_id = providerForm.provider_id
  if (providerForm.api_key) payload.api_key = providerForm.api_key
  return payload
}

async function loadAll(options = {}) {
  errorMessage.value = ''
  await loadModelProviderWorkspace(options)
  if (modelProviderStore.error) errorMessage.value = modelProviderStore.error
  if (activeProviderId.value) fillProviderForm(activeProvider.value)
}

async function saveProvider() {
  saving.value = true
  statusMessage.value = ''
  errorMessage.value = ''
  try {
    const payload = buildProviderPayload()
    if (activeProviderId.value) {
      await updateModelProvider(activeProviderId.value, payload)
      statusMessage.value = 'Provider 配置已保存'
    } else {
      await createModelProvider(payload)
      activeProviderId.value = payload.provider_id
      statusMessage.value = 'Provider 已新增'
    }
    await refreshModelCache()
    await loadAll({ force: true })
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    saving.value = false
  }
}

async function toggleProvider(provider = activeProvider.value) {
  if (!provider) return
  await updateModelProvider(provider.provider_id, { is_enabled: !provider.is_enabled })
  await refreshModelCache()
  await loadAll({ force: true })
  statusMessage.value = `${provider.display_name} 已${provider.is_enabled ? '停用' : '启用'}`
}

function normalizedModelFromForm() {
  const model = {
    id: modelForm.id.trim(),
    display_name: modelForm.id.trim(),
    type: modelForm.type,
    source: 'manual',
  }
  if (model.type === 'embedding' && modelForm.dimension) {
    model.dimension = Number(modelForm.dimension)
  } else if (model.type === 'chat' && modelForm.dimension) {
    model.context_length = Number(modelForm.dimension)
  }
  return model
}

async function addModel() {
  if (!activeProvider.value) return
  const nextModel = normalizedModelFromForm()
  await addModelToProvider(nextModel)
  Object.assign(modelForm, { id: '', type: 'chat', dimension: '' })
}

async function addModelToProvider(nextModel) {
  if (!activeProvider.value) return
  if (!nextModel.id) return
  const enabled = activeProvider.value.enabled_models || []
  if (enabled.some((item) => item.id === nextModel.id && item.type === nextModel.type)) {
    errorMessage.value = '模型已存在'
    return
  }
  await updateModelProvider(activeProvider.value.provider_id, {
    enabled_models: [...enabled, nextModel],
  })
  await refreshModelCache()
  await loadAll({ force: true })
}

async function addRemoteModel(model) {
  if (isModelEnabled(model)) return
  const remoteModel = {
    ...model,
    id: String(model.id || '').trim(),
    display_name: model.display_name || model.name || model.id,
    type: model.type || 'chat',
    source: 'remote',
  }
  await addModelToProvider(remoteModel)
}

async function removeModel(model) {
  if (!activeProvider.value) return
  await updateModelProvider(activeProvider.value.provider_id, {
    enabled_models: (activeProvider.value.enabled_models || []).filter(
      (item) => !(item.id === model.id && item.type === model.type),
    ),
  })
  await refreshModelCache()
  await loadAll({ force: true })
}

async function testModel(model) {
  if (!activeProvider.value) return
  const spec = `${activeProvider.value.provider_id}:${model.id}`
  testingSpec.value = spec
  errorMessage.value = ''
  try {
    const result = await testProviderModel(activeProvider.value.provider_id, {
      model_id: model.id,
      model_type: model.type || 'chat',
    })
    lastTestResult.value = result
    modelTestResults[spec] = result
    if (result.status === 'available') {
      statusMessage.value = `${model.display_name || model.id} 模型调用成功`
    } else {
      errorMessage.value = `${model.display_name || model.id}：${result.message || '模型不可用'}`
    }
  } catch (error) {
    modelTestResults[spec] = { status: 'error', message: error.message }
    errorMessage.value = error.message
  } finally {
    testingSpec.value = ''
  }
}

async function testCredentials() {
  credentialTesting.value = true
  statusMessage.value = ''
  errorMessage.value = ''
  const testedSignature = currentCredentialSignature.value
  try {
    const payload = {
      provider_id: activeProviderId.value || providerForm.provider_id || null,
      base_url: providerForm.base_url.trim(),
      models_endpoint: providerForm.models_endpoint.trim(),
      api_key_env: providerForm.api_key_env.trim() || null,
      headers_json: parseJson(providerForm.headersText, 'Headers JSON'),
    }
    if (providerForm.api_key) payload.api_key = providerForm.api_key
    const result = await testModelProviderCredentials(payload)
    credentialTestResult.value = result
    credentialTestSignature.value = testedSignature
    statusMessage.value = result.message
  } catch (error) {
    credentialTestResult.value = { status: 'error', message: error.message }
    credentialTestSignature.value = testedSignature
    errorMessage.value = error.message
  } finally {
    credentialTesting.value = false
  }
}

function credentialSourceLabel(source) {
  return {
    current_input: '当前输入',
    saved: '已保存凭证',
    environment: '环境变量',
    custom_header: 'Authorization Header',
  }[source] || '未知来源'
}

function modelTestResult(model) {
  return modelTestResults[`${activeProvider.value?.provider_id}:${model.id}`]
}

function modelTestTitle(model) {
  const result = modelTestResult(model)
  if (!result) return `测试 ${model.display_name || model.id}`
  return result.status === 'available'
    ? `${model.display_name || model.id} 最近测试成功`
    : `${model.display_name || model.id}：${result.message || '最近测试失败'}`
}

async function loadRemoteModels() {
  if (!activeProvider.value) return
  remoteLoading.value = true
  errorMessage.value = ''
  remoteModalOpen.value = true
  try {
    remoteModels.value = await fetchRemoteModels(activeProvider.value.provider_id)
    statusMessage.value = `已获取 ${remoteModels.value.length} 个远端模型`
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    remoteLoading.value = false
  }
}

function closeRemoteModal() {
  remoteModalOpen.value = false
  remoteKeyword.value = ''
  remoteTypeFilter.value = 'all'
}

async function testProvider(provider) {
  const chatModel = (provider?.enabled_models || []).find((model) => model.type === 'chat')
  if (!provider || !chatModel) {
    statusMessage.value = '没有可测试的 chat 模型'
    return
  }
  fillProviderForm(provider)
  await testModel(chatModel)
}

async function saveModelUse(modelUse, modelSpec) {
  if (!modelSpec) return
  await updateModelUse(modelUse, modelSpec)
  await refreshModelCache()
  await loadAll({ force: true })
  statusMessage.value = `${modelUse} 已更新`
}

async function refreshCache() {
  errorMessage.value = ''
  try {
    await refreshModelCache()
    await loadAll({ force: true })
    statusMessage.value = '模型缓存已刷新'
  } catch (error) {
    errorMessage.value = error.message
  }
}

function copyText(text) {
  if (text) navigator.clipboard?.writeText(text)
}

function closeProviderMenu(event) {
  event.currentTarget.closest('details')?.removeAttribute('open')
}

function closeProviderMenusOnOutsideClick(event) {
  // 原生 details 不会自动处理外部点击，这里只收起点击目标之外的菜单。
  modelPageRef.value?.querySelectorAll('.provider-more-menu[open]').forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute('open')
  })
}

async function loadProviderRemoteModels(provider, event) {
  closeProviderMenu(event)
  fillProviderForm(provider)
  await loadRemoteModels()
}

async function deleteProvider(provider, event) {
  closeProviderMenu(event)
  // 删除属于不可逆操作，保留浏览器原生确认以避免误触。
  if (!window.confirm(`确定删除 Provider「${provider.display_name}」吗？`)) return

  errorMessage.value = ''
  try {
    await deleteModelProvider(provider.provider_id)
    await refreshModelCache()
    await loadAll({ force: true })
    statusMessage.value = `${provider.display_name} 已删除`
  } catch (error) {
    errorMessage.value = error.message
  }
}

onMounted(() => {
  loadAll()
  document.addEventListener('pointerdown', closeProviderMenusOnOutsideClick)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeProviderMenusOnOutsideClick))
onBeforeUnmount(() => {
  window.clearTimeout(statusMessageTimer)
  window.clearTimeout(errorMessageTimer)
  toastTimers.forEach((timer) => window.clearTimeout(timer))
  toastTimers.clear()
})
</script>

<template>
  <section ref="modelPageRef" class="model-page">
    <template v-if="screenMode === 'list'">
      <header class="model-page-heading">
        <div>
          <h1>模型配置</h1>
          <p>统一管理模型供应商、运行用途和启用模型。</p>
        </div>
        <div class="model-page-actions">
          <button class="model-action-button" type="button" @click="refreshCache">
            <RefreshCw :size="16" />
            刷新缓存
          </button>
          <button class="model-action-button primary-action" type="button" @click="openNewProvider">
            <Plus :size="16" />
            新增 Provider
          </button>
        </div>
      </header>

      <div class="model-list-layout">
        <main class="model-list-main">
          <div class="model-list-toolbar">
            <label class="model-search">
              <Search :size="17" />
              <input v-model="keyword" type="search" placeholder="搜索 Provider" />
            </label>
            <div class="model-filter-group">
              <button :class="{ active: statusFilter === 'all' }" type="button" @click="statusFilter = 'all'">全部</button>
              <button :class="{ active: statusFilter === 'enabled' }" type="button" @click="statusFilter = 'enabled'">已启用</button>
              <button :class="{ active: statusFilter === 'disabled' }" type="button" @click="statusFilter = 'disabled'">停用</button>
            </div>
            <div class="model-filter-group">
              <span>模型类型：</span>
              <button :class="{ active: typeFilter === 'all' }" type="button" @click="typeFilter = 'all'">全部</button>
              <button :class="{ active: typeFilter === 'chat' }" type="button" @click="typeFilter = 'chat'">chat</button>
              <button :class="{ active: typeFilter === 'embedding' }" type="button" @click="typeFilter = 'embedding'">embedding</button>
              <button :class="{ active: typeFilter === 'rerank' }" type="button" @click="typeFilter = 'rerank'">rerank</button>
            </div>
            <label v-for="modelUse in RUNTIME_USES" :key="modelUse.key" class="model-runtime-select">
              <span>{{ modelUse.key }}</span>
              <AppSelect
                :model-value="modelUseSpec(modelUse.key)"
                :aria-label="`${modelUse.key} 模型`"
                :options="runtimeModelOptions"
                @update:model-value="saveModelUse(modelUse.key, $event)"
              />
            </label>
          </div>

          <div v-if="loading" class="extension-empty">正在加载模型配置...</div>
          <div v-else class="model-card-grid">
            <article v-for="provider in filteredProviders" :key="provider.provider_id" class="provider-overview-card">
              <header>
                <span class="provider-logo"><ProviderIcon :provider-id="provider.provider_id" :size="26" /></span>
                <div class="provider-identity">
                  <h2>{{ provider.display_name }}</h2>
                  <small>{{ provider.default_protocol || `${provider.provider_type} compatible` }}</small>
                </div>
                <button
                  class="provider-toggle"
                  :class="{ active: provider.is_enabled }"
                  type="button"
                  role="switch"
                  :aria-checked="provider.is_enabled"
                  :aria-label="`${provider.display_name}：${providerToggleLabel(provider)}`"
                  :title="providerToggleLabel(provider)"
                  @click="toggleProvider(provider)"
                ><span /></button>
              </header>

              <div class="provider-model-counts">
                <span>chat<strong :class="{ zero: providerModelCount(provider, 'chat') === 0 }">{{ providerModelCount(provider, 'chat') }}</strong></span>
                <span>embedding<strong :class="{ zero: providerModelCount(provider, 'embedding') === 0 }">{{ providerModelCount(provider, 'embedding') }}</strong></span>
                <span>rerank<strong :class="{ zero: providerModelCount(provider, 'rerank') === 0 }">{{ providerModelCount(provider, 'rerank') }}</strong></span>
              </div>

              <div class="provider-meta">
                <span>Base URL</span>
                <p :title="provider.base_url">{{ provider.base_url }}</p>
              </div>

              <footer>
                <button type="button" class="detail-outline" @click="openProviderDetail(provider)">配置</button>
                <button type="button" @click="testProvider(provider)">测试</button>
                <details class="provider-more-menu">
                  <summary title="更多操作" aria-label="更多操作"><MoreHorizontal :size="18" /></summary>
                  <div>
                    <button type="button" @click="loadProviderRemoteModels(provider, $event)">获取远端模型</button>
                    <button type="button" @click="copyText(provider.base_url); closeProviderMenu($event)">复制 Base URL</button>
                    <button type="button" class="danger" @click="deleteProvider(provider, $event)">删除 Provider</button>
                  </div>
                </details>
              </footer>
            </article>
          </div>
        </main>
      </div>
    </template>

    <template v-else>
      <header class="provider-detail-hero">
        <nav>
          <Home :size="15" />
          <button type="button" @click="backToList">模型配置</button>
          <span>/</span>
          <strong>{{ providerForm.display_name || 'Provider' }}</strong>
        </nav>
        <div class="detail-title-row">
          <span class="detail-provider-logo"><ProviderIcon :provider-id="providerForm.provider_id" :size="36" /></span>
          <h1>{{ providerForm.display_name || 'Provider' }}</h1>
          <em>provider_id: {{ providerForm.provider_id }}</em>
          <i :class="{ muted: !providerForm.is_enabled }">{{ providerForm.is_enabled ? '已启用' : '已停用' }}</i>
          <small>{{ providerFormModels.length }} models</small>
          <div class="detail-actions">
            <button class="model-action-button" type="button" @click="backToList">
              <ArrowLeft :size="16" />
              返回列表
            </button>
          </div>
        </div>
      </header>

      <div class="provider-detail-layout">
        <main class="provider-form-panel">
          <section class="form-section">
            <h2>基础信息</h2>
            <div class="model-form-grid">
              <label><span>Provider ID</span><input v-model="providerForm.provider_id" :disabled="Boolean(activeProviderId)" /></label>
              <label><span>显示名称</span><input v-model="providerForm.display_name" /></label>
              <label>
                <span>Provider Type</span>
                <AppSelect
                  v-model="providerForm.provider_type"
                  aria-label="Provider Type"
                  :options="providerTypeOptions"
                />
              </label>
              <label><span>默认协议</span><input v-model="providerForm.default_protocol" /></label>
              <label class="wide"><span>能力</span><input v-model="providerForm.capabilitiesText" placeholder="chat, embedding, rerank" /></label>
            </div>
          </section>

          <section class="form-section">
            <header class="form-section-heading">
              <h2>认证配置</h2>
              <div class="form-section-actions">
                <button
                  class="model-action-button compact-action"
                  type="button"
                  :disabled="credentialTesting || !providerForm.base_url.trim() || !providerForm.models_endpoint.trim()"
                  @click="testCredentials"
                >
                  <KeyRound :size="15" />
                  {{ credentialTesting ? '验证中...' : '验证凭证' }}
                </button>
                <button
                  class="model-action-button primary-action compact-action"
                  type="button"
                  :disabled="saving"
                  @click="saveProvider"
                >
                  <Save :size="15" />
                  保存
                </button>
              </div>
            </header>
            <div class="model-form-grid">
              <label><span>API Key 环境变量</span><input v-model="providerForm.api_key_env" /></label>
              <label class="api-key-field">
                <span>API Key</span>
                <input v-model="providerForm.api_key" :type="showApiKey ? 'text' : 'password'" placeholder="留空则不修改" />
                <button type="button" @click="showApiKey = !showApiKey">
                  <EyeOff v-if="showApiKey" :size="16" />
                  <Eye v-else :size="16" />
                </button>
              </label>
            </div>
            <div
              class="credential-test-feedback"
              :class="credentialTestState"
              :role="credentialTestState === 'error' ? 'alert' : 'status'"
              aria-live="polite"
            >
              <KeyRound :size="15" />
              <span v-if="credentialTestState === 'idle'">使用当前表单值验证，不会保存或缓存 API Key。</span>
              <span v-else-if="credentialTestState === 'testing'">正在访问 Models Endpoint...</span>
              <span v-else-if="credentialTestState === 'stale'">认证配置已更改，请重新验证。</span>
              <span v-else-if="credentialTestState === 'success'">
                {{ credentialTestResult.message }} · {{ credentialSourceLabel(credentialTestResult.credential_source) }}
                · {{ credentialTestResult.remote_model_count }} 个模型 · {{ credentialTestResult.latency_ms }} ms
              </span>
              <span v-else>{{ credentialTestResult?.message || '凭证验证失败' }}</span>
            </div>
          </section>

          <section class="form-section">
            <h2>端点配置</h2>
            <div class="model-form-grid">
              <label><span>Base URL</span><input v-model="providerForm.base_url" /></label>
              <label><span>Models Endpoint</span><input v-model="providerForm.models_endpoint" /></label>
              <label><span>Embedding Base URL</span><input v-model="providerForm.embedding_base_url" /></label>
              <label><span>Embedding Endpoint</span><input v-model="providerForm.embedding_models_endpoint" /></label>
              <label><span>Rerank Base URL</span><input v-model="providerForm.rerank_base_url" /></label>
              <label><span>Rerank Endpoint</span><input v-model="providerForm.rerank_models_endpoint" /></label>
            </div>
          </section>

          <details class="form-section advanced-config-section">
            <summary>
              <span>高级配置</span>
              <ChevronDown :size="17" />
            </summary>
            <div class="model-form-grid">
              <label><span>Headers JSON</span><textarea v-model="providerForm.headersText" rows="4" /></label>
              <label><span>Extra JSON</span><textarea v-model="providerForm.extraText" rows="4" /></label>
            </div>
          </details>
        </main>

        <aside class="provider-side-panel">
          <section class="side-card">
            <header>
              <h2>模型列表</h2>
              <button class="model-action-button compact-action" type="button" :disabled="!activeProvider || remoteLoading" @click="loadRemoteModels">
                <CloudDownload :size="15" />
                {{ remoteLoading ? '获取中' : '远端获取' }}
              </button>
            </header>
            <div class="detail-model-add-row">
              <input v-model="modelForm.id" placeholder="例如 qwen-plus" />
              <AppSelect
                v-model="modelForm.type"
                aria-label="模型类型"
                :options="modelTypeOptions"
              />
              <input v-model="modelForm.dimension" placeholder="例如 1024" />
              <button type="button" class="model-action-button primary-action" @click="addModel">添加</button>
            </div>

            <div class="detail-model-table">
              <div class="detail-model-row head">
                <span>模型</span>
                <span>类型</span>
                <span>上下文长度</span>
                <span>来源</span>
                <span>操作</span>
              </div>
              <div v-if="!providerFormModels.length" class="detail-model-empty">暂无模型</div>
              <div v-for="model in paginatedProviderModels" :key="`${model.type}:${model.id}`" class="detail-model-row">
                <span><strong>{{ model.display_name || model.id }}</strong><code>{{ model.id }}</code></span>
                <span>{{ model.type }}</span>
                <span>{{ model.context_length || model.dimension || '-' }}</span>
                <span>{{ model.source || 'manual' }}</span>
                <span>
                  <button
                    class="icon-button model-test-button"
                    :class="{
                      success: modelTestResult(model)?.status === 'available',
                      failed: modelTestResult(model) && modelTestResult(model).status !== 'available',
                    }"
                    type="button"
                    :title="modelTestTitle(model)"
                    :aria-label="modelTestTitle(model)"
                    :disabled="testingSpec === `${activeProvider?.provider_id}:${model.id}`"
                    @click="testModel(model)"
                  >
                    <FlaskConical :size="15" />
                  </button>
                  <button class="icon-button danger" type="button" @click="removeModel(model)">
                    <Trash2 :size="15" />
                  </button>
                </span>
              </div>
            </div>
            <footer class="detail-model-pagination">
              <span>共 {{ providerFormModels.length }} 条</span>
              <AppSelect
                v-model="modelPageSize"
                class="detail-model-page-size"
                aria-label="每页模型数量"
                :options="modelPageSizeOptions"
              />
              <nav class="detail-model-page-buttons" aria-label="模型列表分页">
                <button
                  type="button"
                  aria-label="上一页"
                  :disabled="modelPage <= 1"
                  @click="modelPage -= 1"
                >
                  <ChevronLeft :size="16" />
                </button>
                <button
                  v-for="page in visibleModelPages"
                  :key="page"
                  type="button"
                  :class="{ active: modelPage === page }"
                  :aria-current="modelPage === page ? 'page' : undefined"
                  @click="modelPage = page"
                >
                  {{ page }}
                </button>
                <button
                  type="button"
                  aria-label="下一页"
                  :disabled="modelPage >= modelPageCount"
                  @click="modelPage += 1"
                >
                  <ChevronRight :size="16" />
                </button>
              </nav>
            </footer>
          </section>

        </aside>
      </div>
    </template>

    <div v-if="remoteModalOpen" class="remote-model-modal-backdrop" @click.self="closeRemoteModal">
      <section class="remote-model-modal" role="dialog" aria-modal="true" aria-label="远端模型">
        <header>
          <div>
            <h2>远端模型</h2>
            <p>{{ activeProvider?.display_name || providerForm.display_name || 'Provider' }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭远端模型弹窗" @click="closeRemoteModal">
            <X :size="16" />
          </button>
        </header>

        <div class="remote-model-modal-toolbar">
          <label class="model-search">
            <Search :size="16" />
            <input v-model="remoteKeyword" type="search" placeholder="搜索模型" />
          </label>
          <div class="model-filter-group compact-filter">
            <button :class="{ active: remoteTypeFilter === 'all' }" type="button" @click="remoteTypeFilter = 'all'">全部</button>
            <button :class="{ active: remoteTypeFilter === 'chat' }" type="button" @click="remoteTypeFilter = 'chat'">chat</button>
            <button :class="{ active: remoteTypeFilter === 'embedding' }" type="button" @click="remoteTypeFilter = 'embedding'">embedding</button>
            <button :class="{ active: remoteTypeFilter === 'rerank' }" type="button" @click="remoteTypeFilter = 'rerank'">rerank</button>
          </div>
        </div>

        <div class="remote-model-table">
          <div class="remote-model-row head">
            <span>模型</span>
            <span>类型</span>
            <span>维度</span>
            <span>来源</span>
            <span>操作</span>
          </div>
          <div v-if="remoteLoading" class="remote-model-empty">正在获取远端模型...</div>
          <div v-else-if="!filteredRemoteModels.length" class="remote-model-empty">没有匹配的远端模型</div>
          <template v-else>
            <div
              v-for="model in filteredRemoteModels"
              :key="`${model.type || 'chat'}:${model.id}`"
              class="remote-model-row"
            >
              <span><strong>{{ model.display_name || model.name || model.id }}</strong><code>{{ model.id }}</code></span>
              <span>{{ model.type || 'chat' }}</span>
              <span>{{ model.dimension || '-' }}</span>
              <span>remote</span>
              <span>
                <button
                  class="model-action-button compact-action"
                  type="button"
                  :disabled="isModelEnabled(model)"
                  @click="addRemoteModel(model)"
                >
                  {{ isModelEnabled(model) ? '已添加' : '添加' }}
                </button>
              </span>
            </div>
          </template>
        </div>

        <footer>
          <button class="model-action-button" type="button" @click="closeRemoteModal">关闭</button>
        </footer>
      </section>
    </div>

    <TransitionGroup name="model-toast" tag="div" class="model-toast-stack">
      <p
        v-for="toast in modelToasts"
        :key="toast.id"
        :class="toast.type === 'success' ? 'model-status-message' : 'model-error-message'"
      >
        <span class="model-toast-icon" :class="toast.type">
          <Check v-if="toast.type === 'success'" :size="12" />
          <X v-else :size="12" />
        </span>
        <span>{{ toast.message }}</span>
      </p>
    </TransitionGroup>
  </section>
</template>
