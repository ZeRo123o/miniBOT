<script setup>
import { Check, PanelRightClose, PanelRightOpen } from 'lucide-vue-next'
import { computed } from 'vue'
import {
  persistSelection,
  refreshSelectionDirtyState,
  selectionStore,
} from '../stores/selectionStore'

defineProps({
  collapsed: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['toggle'])

const knowledgeBases = computed(() => selectionStore.resources.knowledgeBase || [])
const selectedKnowledgeBaseIds = computed(
  () => selectionStore.selection.knowledge_base_ids || [],
)

function resourceTitle(item) {
  return item.display_name || item.name
}

function resourceInitial(item) {
  return String(resourceTitle(item) || 'K').trim().charAt(0).toUpperCase()
}

function toggleKnowledgeBase(knowledgeBaseId) {
  const selected = new Set(selectionStore.selection.knowledge_base_ids)
  if (selected.has(knowledgeBaseId)) selected.delete(knowledgeBaseId)
  else selected.add(knowledgeBaseId)
  selectionStore.selection.knowledge_base_ids = Array.from(selected)
  refreshSelectionDirtyState()
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
      <section class="resource-card">
        <header class="resource-card-header">
          <div>
            <h2>知识库</h2>
            <p>选择当前对话可以查询的知识库。</p>
          </div>
          <span>{{ selectedKnowledgeBaseIds.length }}/{{ knowledgeBases.length }}</span>
        </header>

        <div class="resource-list">
          <label
            v-for="item in knowledgeBases"
            :key="`knowledgeBase:${item.id}`"
            class="resource-row"
            :class="{ selected: selectedKnowledgeBaseIds.includes(item.id) }"
          >
            <input
              class="resource-checkbox"
              type="checkbox"
              :checked="selectedKnowledgeBaseIds.includes(item.id)"
              :aria-label="`选择知识库 ${resourceTitle(item)}`"
              @change="toggleKnowledgeBase(item.id)"
            />
            <span class="resource-avatar" aria-hidden="true">{{ resourceInitial(item) }}</span>
            <span class="resource-copy">
              <strong>{{ resourceTitle(item) }}</strong>
              <small>KB #{{ item.id }}</small>
            </span>
            <span class="resource-check" aria-hidden="true">
              <Check v-if="selectedKnowledgeBaseIds.includes(item.id)" :size="14" />
            </span>
          </label>
          <p v-if="!knowledgeBases.length" class="empty">暂无可选知识库。</p>
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
