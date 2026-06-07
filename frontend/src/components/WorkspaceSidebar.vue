<script setup>
import { PanelRightClose, PanelRightOpen } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { persistSelection, selectionStore } from '../stores/selectionStore'

defineProps({
  collapsed: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['toggle'])

const tabs = [
  { key: 'mcps', resourceKey: 'mcp', label: 'MCP' },
  { key: 'subagents', resourceKey: 'subagent', label: 'Subagent' },
  { key: 'skills', resourceKey: 'skill', label: 'Skill' },
  { key: 'knowledge_base_ids', resourceKey: 'knowledgeBase', label: '知识库', valueKey: 'id' },
]

const activeTab = ref('mcps')

const activeConfig = computed(() => tabs.find((tab) => tab.key === activeTab.value) || tabs[0])
const activeItems = computed(() => selectionStore.resources[activeConfig.value.resourceKey] || [])
const activeSelection = computed(() => selectionStore.selection[activeConfig.value.key] || [])

function resourceValue(item) {
  return activeConfig.value.valueKey ? item[activeConfig.value.valueKey] : item.name
}

function resourceTitle(item) {
  return item.display_name || item.name
}

function resourceKey(item) {
  return `${activeConfig.value.resourceKey}:${resourceValue(item)}`
}

function toggleResource(value) {
  const key = activeConfig.value.key
  const selected = new Set(selectionStore.selection[key])
  if (selected.has(value)) selected.delete(value)
  else selected.add(value)
  selectionStore.selection[key] = Array.from(selected)
  selectionStore.hasUnsavedChanges = true
}
</script>

<template>
  <aside class="workspace-sidebar" :class="{ collapsed }">
    <header class="workspace-sidebar-header">
      <button
        class="sidebar-toggle"
        type="button"
        :title="collapsed ? '展开工作区' : '折叠工作区'"
        @click="$emit('toggle')"
      >
        <PanelRightOpen v-if="collapsed" :size="18" />
        <PanelRightClose v-else :size="18" />
      </button>
      <h1 v-if="!collapsed">工作区</h1>
    </header>

    <div v-if="!collapsed" class="workspace-sidebar-body">
      <div class="resource-tabs" role="tablist" aria-label="资源类型">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          type="button"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <section class="resource-card">
        <header class="resource-card-header">
          <div>
            <h2>{{ activeConfig.label }}</h2>
            <p>选择当前对话运行时启用的 {{ activeConfig.label }} 资源。</p>
          </div>
          <span>{{ activeSelection.length }}/{{ activeItems.length }}</span>
        </header>

        <div class="resource-list">
          <label v-for="item in activeItems" :key="resourceKey(item)" class="resource-row">
            <input
              type="checkbox"
              :checked="activeSelection.includes(resourceValue(item))"
              @change="toggleResource(resourceValue(item))"
            />
            <span>
              <strong>{{ resourceTitle(item) }}</strong>
              <small>{{ activeConfig.valueKey ? `KB #${item.id}` : item.name }}</small>
              <em>{{ item.description }}</em>
            </span>
          </label>
          <p v-if="!activeItems.length" class="empty">暂无可选资源。</p>
        </div>
      </section>

      <p v-if="selectionStore.error" class="resource-error">{{ selectionStore.error }}</p>
      <button
        class="workspace-save-button"
        :class="{ pending: selectionStore.hasUnsavedChanges }"
        :disabled="selectionStore.loading || !selectionStore.hasUnsavedChanges"
        @click="persistSelection"
      >
        {{ selectionStore.loading ? '保存中...' : '保存' }}
      </button>
    </div>
  </aside>
</template>
