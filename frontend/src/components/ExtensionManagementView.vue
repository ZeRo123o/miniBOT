<script setup>
import { Blocks, Bot, Plug, Search, Wrench } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { listResources, upsertResource } from '../apis/resources'

const categories = [
  { key: 'tool', label: '工具', icon: Wrench },
  { key: 'mcp', label: 'MCP', icon: Plug },
  { key: 'skill', label: 'Skill', icon: Blocks },
  { key: 'subagent', label: 'Subagent', icon: Bot },
]

const activeCategory = ref('tool')
const resourcesByKind = ref({
  tool: [],
  mcp: [],
  skill: [],
  subagent: [],
})
const keyword = ref('')
const loading = ref(false)
const updatingName = ref('')
const errorMessage = ref('')

const activeConfig = computed(
  () => categories.find((category) => category.key === activeCategory.value) || categories[0],
)

const filteredResources = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  const resources = resourcesByKind.value[activeCategory.value] || []
  if (!query) return resources
  return resources.filter((resource) =>
    [resource.name, resource.display_name, resource.description]
      .some((value) => String(value || '').toLowerCase().includes(query)),
  )
})

async function loadResources() {
  loading.value = true
  errorMessage.value = ''
  try {
    const results = await Promise.all(
      categories.map((category) => listResources(category.key)),
    )
    categories.forEach((category, index) => {
      resourcesByKind.value[category.key] = results[index]
    })
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    loading.value = false
  }
}

async function toggleResource(resource) {
  if (updatingName.value) return
  updatingName.value = resource.name
  errorMessage.value = ''
  try {
    const updated = await upsertResource({
      kind: resource.kind,
      name: resource.name,
      display_name: resource.display_name,
      description: resource.description || '',
      enabled: !resource.enabled,
      config: resource.config || {},
    })
    const resources = resourcesByKind.value[resource.kind] || []
    const index = resources.findIndex((item) => item.name === resource.name)
    if (index !== -1) resources[index] = updated
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    updatingName.value = ''
  }
}

onMounted(loadResources)
</script>

<template>
  <section class="extension-page">
    <header class="extension-header">
      <div>
        <span class="extension-eyebrow">Extensions</span>
        <h1>扩展管理</h1>
        <p>查看并管理 Agent 可使用的工具与扩展资源。</p>
      </div>
      <label class="extension-search">
        <Search :size="17" />
        <input v-model="keyword" type="search" placeholder="搜索名称、标识或描述" />
      </label>
    </header>

    <nav class="extension-tabs" aria-label="扩展类型">
      <button
        v-for="category in categories"
        :key="category.key"
        type="button"
        :class="{ active: activeCategory === category.key }"
        @click="activeCategory = category.key"
      >
        <component :is="category.icon" :size="17" />
        <span>{{ category.label }}</span>
        <em>{{ resourcesByKind[category.key].length }}</em>
      </button>
    </nav>

    <div class="extension-summary">
      <div>
        <h2>{{ activeConfig.label }}</h2>
        <p>已启用 {{ resourcesByKind[activeCategory].filter((item) => item.enabled).length }} 个，共 {{ resourcesByKind[activeCategory].length }} 个。</p>
      </div>
    </div>

    <div v-if="loading" class="extension-empty">正在加载扩展资源...</div>
    <div v-else-if="!filteredResources.length" class="extension-empty">暂无匹配的扩展资源。</div>
    <div v-else class="extension-grid">
      <article
        v-for="resource in filteredResources"
        :key="`${resource.kind}:${resource.name}`"
        class="extension-card"
        :class="{ disabled: !resource.enabled }"
      >
        <header>
          <div class="extension-icon">
            <component :is="activeConfig.icon" :size="20" />
          </div>
          <button
            class="extension-switch"
            type="button"
            role="switch"
            :aria-checked="resource.enabled"
            :aria-label="`${resource.enabled ? '停用' : '启用'} ${resource.display_name}`"
            :disabled="updatingName === resource.name"
            :class="{ active: resource.enabled }"
            @click="toggleResource(resource)"
          >
            <span />
          </button>
        </header>
        <div class="extension-card-body">
          <div class="extension-name-row">
            <h3>{{ resource.display_name || resource.name }}</h3>
            <div class="extension-badges">
              <span
                v-if="resource.kind === 'tool' && resource.config?.category === 'buildin'"
                class="builtin"
              >
                内置工具
              </span>
              <span :class="{ enabled: resource.enabled }">
                {{ resource.enabled ? '已启用' : '已停用' }}
              </span>
            </div>
          </div>
          <code>{{ resource.name }}</code>
          <p>{{ resource.description || '暂无描述。' }}</p>
        </div>
      </article>
    </div>

    <p v-if="errorMessage" class="extension-error">{{ errorMessage }}</p>
  </section>
</template>
