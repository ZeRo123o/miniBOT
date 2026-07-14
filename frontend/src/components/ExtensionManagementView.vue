<script setup>
import { Blocks, Plug, Search, Wrench } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { upsertResource } from '../apis/resources'
import AppSelect from './AppSelect.vue'
import {
  extensionResourceStore,
  loadExtensionResources,
  updateCachedExtensionResource,
} from '../stores/extensionResourceStore'

const categories = [
  { key: 'tool', label: '工具', icon: Wrench },
  { key: 'mcp', label: 'MCP', icon: Plug },
  { key: 'skill', label: 'Skill', icon: Blocks },
]

const activeCategory = ref('tool')
const resourcesByKind = computed(() => extensionResourceStore.resourcesByKind)
const keyword = ref('')
const statusFilter = ref('all')
const loading = computed(() => extensionResourceStore.loading)
const updatingName = ref('')
const errorMessage = computed(() => extensionResourceStore.error)

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'enabled', label: '已启用' },
  { value: 'disabled', label: '已停用' },
]

function resourceKey(resource) {
  return resource.kind === 'skill' ? resource.slug : resource.name
}

function resourceTitle(resource) {
  return resource.kind === 'skill'
    ? resource.name || resource.slug
    : resource.display_name || resource.name
}

function isBuiltinTool(resource) {
  return resource.kind === 'tool'
    && resource.config?.origin === 'builtin'
}

const activeConfig = computed(
  () => categories.find((category) => category.key === activeCategory.value) || categories[0],
)

const filteredResources = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  const resources = resourcesByKind.value[activeCategory.value] || []
  return resources.filter((resource) => {
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'enabled' && resource.enabled)
      || (statusFilter.value === 'disabled' && !resource.enabled)
    if (!matchesStatus) return false
    if (!query) return true
    return [resourceKey(resource), resourceTitle(resource), resource.description]
      .some((value) => String(value || '').toLowerCase().includes(query))
  })
})

async function toggleResource(resource) {
  if (resource.kind === 'skill') return
  if (updatingName.value) return
  updatingName.value = resource.name
  extensionResourceStore.error = ''
  try {
    const updated = await upsertResource({
      kind: resource.kind,
      name: resource.name,
      display_name: resource.display_name,
      description: resource.description || '',
      enabled: !resource.enabled,
      config: resource.config || {},
    })
    updateCachedExtensionResource(resource.kind, updated)
  } catch (error) {
    extensionResourceStore.error = error.message
  } finally {
    updatingName.value = ''
  }
}

onMounted(loadExtensionResources)
</script>

<template>
  <section class="extension-page">
    <header class="extension-header">
      <div class="extension-title">
        <h1>扩展管理</h1>
        <p>管理 Agent 可使用的工具、MCP 与技能资源。</p>
      </div>
      <div class="extension-header-controls">
        <label class="extension-search">
          <Search :size="16" />
          <input v-model="keyword" type="search" placeholder="搜索名称或描述" />
        </label>
        <AppSelect
          v-model="statusFilter"
          class="extension-status-filter"
          aria-label="扩展状态"
          :options="statusOptions"
        />
      </div>
    </header>

    <nav class="extension-tabs" aria-label="扩展类型">
      <button
        v-for="category in categories"
        :key="category.key"
        type="button"
        :class="{ active: activeCategory === category.key }"
        @click="activeCategory = category.key"
      >
        <span>{{ category.label }}</span>
        <em>{{ resourcesByKind[category.key].length }}</em>
      </button>
    </nav>

    <div v-if="loading" class="extension-empty">正在加载扩展资源...</div>
    <div v-else-if="!filteredResources.length" class="extension-empty">暂无匹配的扩展资源。</div>
    <div v-else class="extension-grid">
      <article
        v-for="(resource, resourceIndex) in filteredResources"
        :key="`${resource.kind}:${resourceKey(resource)}`"
        class="extension-card"
        :class="{ disabled: !resource.enabled }"
      >
        <header>
          <div class="extension-card-identity">
            <div class="extension-icon" :class="`tone-${resourceIndex % 6}`">
              <component :is="activeConfig.icon" :size="19" />
            </div>
            <div class="extension-name-row">
              <h3 :title="resourceTitle(resource)">{{ resourceTitle(resource) }}</h3>
              <div class="extension-badges">
                <span v-if="isBuiltinTool(resource)" class="builtin">内置工具</span>
                <span v-if="resource.kind === 'skill' && resource.is_builtin" class="builtin">
                  内置 Skill
                </span>
              </div>
            </div>
          </div>
          <button
            v-if="resource.kind !== 'skill'"
            class="extension-switch"
            type="button"
            role="switch"
            :aria-checked="resource.enabled"
            :aria-label="`${resource.enabled ? '停用' : '启用'} ${resourceTitle(resource)}`"
            :disabled="updatingName === resource.name"
            :class="{ active: resource.enabled }"
            @click="toggleResource(resource)"
          >
            <span />
          </button>
          <span v-else class="extension-skill-state">可用</span>
        </header>
        <p class="extension-card-description" :title="resource.description || '暂无描述。'">
          {{ resource.description || '暂无描述。' }}
        </p>
      </article>
    </div>

    <p v-if="errorMessage" class="extension-error">{{ errorMessage }}</p>
  </section>
</template>
