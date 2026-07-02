<script setup>
import {
  ArrowLeft,
  Box,
  CheckCircle2,
  CircleAlert,
  CloudDownload,
  Copy,
  X,
  Eye,
  EyeOff,
  FlaskConical,
  Home,
  KeyRound,
  List,
  MessageCircle,
  PlayCircle,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
} from 'lucide-vue-next'
import { computed, onMounted, reactive, ref } from 'vue'
import {
  createModelProvider,
  fetchRemoteModels,
  getModelStatus,
  refreshModelCache,
  updateModelProvider,
  updateModelUse,
} from '../apis/modelProviders'
import {
  loadModelProviderWorkspace,
  modelProviderStore,
} from '../stores/modelProviderStore'

const RUNTIME_USES = [
  { key: 'chat_model', icon: MessageCircle },
  { key: 'deep_research_model', icon: Search },
]

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
const remoteModels = ref([])

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

const testStatusClass = computed(() => ({
  ok: lastTestResult.value?.status === 'available',
  error: lastTestResult.value && lastTestResult.value.status !== 'available',
}))

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

const summary = computed(() => {
  const enabledProviders = providers.value.filter((provider) => provider.is_enabled)
  return {
    providerTotal: providers.value.length,
    enabledProviderTotal: enabledProviders.length,
    enabledModelTotal: providers.value.reduce(
      (total, provider) => total + (provider.enabled_models?.length || 0),
      0,
    ),
    modelUseTotal: modelUses.value.filter((item) => item.model_spec).length,
  }
})

const recentActions = computed(() => [
  {
    title: '更新运行用途',
    detail: modelLabel(modelUseSpec('chat_model')),
    time: '刚刚',
    level: 'ok',
  },
  {
    title: '模型缓存',
    detail: statusMessage.value || '等待刷新或测试',
    time: '',
    level: statusMessage.value ? 'ok' : 'idle',
  },
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

function providerEnabledLabel(provider) {
  return provider?.is_enabled ? '已启用' : '已停用'
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
    const result = await getModelStatus(spec)
    lastTestResult.value = result
    statusMessage.value = `${spec}: ${result.message || result.status}`
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    testingSpec.value = ''
  }
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

onMounted(loadAll)
</script>

<template>
  <section class="model-page">
    <template v-if="screenMode === 'list'">
      <header class="model-page-heading">
        <div>
          <span>MODELS</span>
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

      <div class="model-use-banner">
        <h2>运行用途</h2>
        <label v-for="modelUse in RUNTIME_USES" :key="modelUse.key">
          <span class="use-icon"><component :is="modelUse.icon" :size="17" /></span>
          <span class="use-name">{{ modelUse.key }}</span>
          <i>已启用</i>
          <select :value="modelUseSpec(modelUse.key)" @change="saveModelUse(modelUse.key, $event.target.value)">
            <option value="">未选择</option>
            <option v-for="model in chatModelOptions" :key="`${modelUse.key}:${model.spec}`" :value="model.spec">
              {{ model.provider_display_name }} / {{ model.display_name }}
            </option>
          </select>
        </label>
      </div>

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
          </div>

          <div v-if="loading" class="extension-empty">正在加载模型配置...</div>
          <div v-else class="model-card-grid">
            <article v-for="provider in filteredProviders" :key="provider.provider_id" class="provider-overview-card">
              <header>
                <span class="provider-logo"><Box :size="28" /></span>
                <div>
                  <h2>{{ provider.display_name }}</h2>
                </div>
                <div class="provider-badges">
                  <span :class="{ muted: !provider.is_enabled }">{{ providerEnabledLabel(provider) }}</span>
                </div>
              </header>

              <div class="provider-model-counts">
                <span>chat<strong>{{ providerModelCount(provider, 'chat') }}</strong></span>
                <span>embedding<strong>{{ providerModelCount(provider, 'embedding') }}</strong></span>
                <span>rerank<strong>{{ providerModelCount(provider, 'rerank') }}</strong></span>
              </div>

              <div class="provider-meta">
                <span>Base URL</span>
                <p>{{ provider.base_url }}</p>
                <button type="button" title="复制 Base URL" @click="copyText(provider.base_url)">
                  <Copy :size="14" />
                </button>
              </div>

              <footer>
                <button type="button" @click="testProvider(provider)">
                  <FlaskConical :size="15" />
                  测试
                </button>
                <button
                  type="button"
                  :class="provider.is_enabled ? 'danger-outline' : 'success-outline'"
                  @click="toggleProvider(provider)"
                >
                  <PlayCircle :size="15" />
                  {{ providerToggleLabel(provider) }}
                </button>
                <button type="button" class="detail-outline" @click="openProviderDetail(provider)">
                  <List :size="15" />
                  详情
                </button>
              </footer>
            </article>
          </div>
        </main>

        <aside class="model-summary-sidebar">
          <section class="summary-card">
            <h2>模型总览</h2>
            <div class="summary-metrics">
              <span><strong>{{ summary.providerTotal }}</strong>Provider 总数</span>
              <span><strong>{{ summary.enabledProviderTotal }}</strong>已启用 Provider</span>
              <span><strong>{{ summary.enabledModelTotal }}</strong>启用模型总数</span>
              <span><strong>{{ summary.modelUseTotal }}</strong>用途模型</span>
            </div>
          </section>

          <section class="summary-card">
            <h2>最近操作</h2>
            <div class="recent-list">
              <span v-for="item in recentActions" :key="item.title">
                <i :class="item.level" />
                <b>{{ item.title }}</b>
                <small>{{ item.detail }}</small>
              </span>
            </div>
          </section>
        </aside>
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
          <span class="detail-provider-logo"><Box :size="30" /></span>
          <h1>{{ providerForm.display_name || 'Provider' }}</h1>
          <em>provider_id: {{ providerForm.provider_id }}</em>
          <i :class="{ muted: !providerForm.is_enabled }">{{ providerForm.is_enabled ? '已启用' : '已停用' }}</i>
          <small>{{ providerFormModels.length }} models</small>
          <div class="detail-actions">
            <button class="model-action-button" type="button" @click="backToList">
              <ArrowLeft :size="16" />
              返回列表
            </button>
            <button v-if="activeProvider" class="model-action-button" type="button" @click="toggleProvider(activeProvider)">
              {{ providerToggleLabel(activeProvider) }}
            </button>
            <button class="model-action-button primary-action" type="button" :disabled="saving" @click="saveProvider">
              <Save :size="16" />
              保存
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
                <select v-model="providerForm.provider_type">
                  <option value="mock">mock</option>
                  <option value="openai">openai</option>
                  <option value="anthropic">anthropic</option>
                  <option value="gemini">gemini</option>
                  <option value="openrouter">openrouter</option>
                </select>
              </label>
              <label><span>默认协议</span><input v-model="providerForm.default_protocol" /></label>
              <label class="wide"><span>能力</span><input v-model="providerForm.capabilitiesText" placeholder="chat, embedding, rerank" /></label>
            </div>
          </section>

          <section class="form-section">
            <h2>认证</h2>
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

          <section class="form-section">
            <h2>高级 JSON</h2>
            <div class="model-form-grid">
              <label><span>Headers JSON</span><textarea v-model="providerForm.headersText" rows="4" /></label>
              <label><span>Extra JSON</span><textarea v-model="providerForm.extraText" rows="4" /></label>
            </div>
          </section>
        </main>

        <aside class="provider-side-panel">
          <section class="side-card">
            <header>
              <h2>已启用模型</h2>
              <button class="model-action-button compact-action" type="button" :disabled="!activeProvider || remoteLoading" @click="loadRemoteModels">
                <CloudDownload :size="15" />
                {{ remoteLoading ? '获取中' : '远端获取' }}
              </button>
            </header>
            <div class="detail-model-add-row">
              <input v-model="modelForm.id" placeholder="例如 qwen-plus" />
              <select v-model="modelForm.type">
                <option value="chat">chat</option>
                <option value="embedding">embedding</option>
                <option value="rerank">rerank</option>
              </select>
              <input v-model="modelForm.dimension" placeholder="例如 1024" />
              <button type="button" class="model-action-button primary-action" @click="addModel">添加</button>
            </div>

            <div class="detail-model-table">
              <div class="detail-model-row head">
                <span>模型</span>
                <span>类型</span>
                <span>维度</span>
                <span>来源</span>
                <span>操作</span>
              </div>
              <div v-for="model in providerFormModels" :key="`${model.type}:${model.id}`" class="detail-model-row">
                <span><strong>{{ model.display_name || model.id }}</strong><code>{{ model.id }}</code></span>
                <span>{{ model.type }}</span>
                <span>{{ model.dimension || '-' }}</span>
                <span>{{ model.source || 'manual' }}</span>
                <span>
                  <button class="icon-button" type="button" :disabled="testingSpec === `${activeProvider?.provider_id}:${model.id}`" @click="testModel(model)">
                    <FlaskConical :size="15" />
                  </button>
                  <button class="icon-button danger" type="button" @click="removeModel(model)">
                    <Trash2 :size="15" />
                  </button>
                </span>
              </div>
            </div>
          </section>

          <section class="side-card">
            <h2>连接状态</h2>
            <div class="connection-status-list">
              <span><b>API Key 来源</b><em>{{ providerForm.api_key_env || (providerForm.api_key ? 'direct' : '未设置') }} <CheckCircle2 :size="15" /></em></span>
              <span><b>缓存刷新</b><em>{{ statusMessage || '等待中' }} <CheckCircle2 :size="15" /></em></span>
              <span>
                <b>连通性测试</b>
                <em :class="testStatusClass">
                  {{ lastTestResult?.message || '未测试' }}
                  <CheckCircle2 v-if="lastTestResult?.status === 'available'" :size="15" />
                  <CircleAlert v-else :size="15" />
                </em>
              </span>
            </div>
            <button class="model-action-button primary-action wide-action" type="button" @click="testProvider(activeProvider)">
              <KeyRound :size="16" />
              测试连接
            </button>
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

    <p v-if="statusMessage" class="model-status-message">{{ statusMessage }}</p>
    <p v-if="errorMessage" class="model-error-message">{{ errorMessage }}</p>
  </section>
</template>
