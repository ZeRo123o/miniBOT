<script setup>
import {
  BarChart3,
  Blocks,
  BookOpenText,
  Box,
  BriefcaseBusiness,
  ChevronDown,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  SquarePen,
} from 'lucide-vue-next'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  conversationStore,
  newConversation,
  removeConversation,
  renameConversation,
  selectConversation,
} from '../stores/conversationStore'
import { selectionStore } from '../stores/selectionStore'

defineProps({
  collapsed: {
    type: Boolean,
    default: false,
  },
  activeView: {
    type: String,
    default: 'chat',
  },
})

const emit = defineEmits(['navigate', 'toggle'])

const openMenuId = ref(null)
const pendingDelete = ref(null)

const navigationItems = [
  { key: 'chat', label: '工作区', icon: BriefcaseBusiness, enabled: true },
  { key: 'knowledge', label: '知识库', icon: BookOpenText, enabled: true },
  { key: 'extensions', label: '扩展管理', icon: Blocks, enabled: true },
  { key: 'models', label: '模型配置', icon: Box, enabled: true },
  { key: 'dashboard', label: 'Dashboard', icon: BarChart3, enabled: false },
]

function navigateTo(item) {
  if (!item.enabled) return
  emit('navigate', item.key)
}

function toggleMenu(conversationId) {
  openMenuId.value = openMenuId.value === conversationId ? null : conversationId
}

function closeConversationMenuOnOutsideClick(event) {
  if (!openMenuId.value) return
  if (event.target.closest('.conversation-more, .conversation-menu')) return
  openMenuId.value = null
}

async function handleRename(conversation) {
  openMenuId.value = null
  const title = window.prompt('重命名对话', conversation.title)
  if (title === null || title.trim() === conversation.title) return
  await renameConversation(conversation.id, selectionStore.userId, title)
}

function requestDelete(conversation) {
  openMenuId.value = null
  pendingDelete.value = conversation
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  const conversationId = pendingDelete.value.id
  pendingDelete.value = null
  await removeConversation(conversationId, selectionStore.userId)
}

function startNewConversation() {
  newConversation()
  emit('navigate', 'chat')
}

async function openConversation(conversationId) {
  emit('navigate', 'chat')
  await selectConversation(conversationId, selectionStore.userId)
}

onMounted(() => document.addEventListener('pointerdown', closeConversationMenuOnOutsideClick))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeConversationMenuOnOutsideClick))
</script>

<template>
  <aside class="conversation-sidebar" :class="{ collapsed }">
    <header class="conversation-sidebar-header">
      <h1 v-if="!collapsed">MiniBOT</h1>
      <button
        class="sidebar-toggle"
        type="button"
        :title="collapsed ? '展开侧边栏' : '折叠侧边栏'"
        @click="$emit('toggle')"
      >
        <PanelLeftOpen v-if="collapsed" :size="18" />
        <PanelLeftClose v-else :size="18" />
      </button>
    </header>

    <div v-if="!collapsed" class="conversation-sidebar-body">
      <button
        class="new-chat-button"
        type="button"
        :disabled="conversationStore.loading"
        @click="startNewConversation"
      >
        <SquarePen :size="18" />
        <span>创建新对话</span>
      </button>

      <nav class="sidebar-nav" aria-label="主导航">
        <button
          v-for="item in navigationItems"
          :key="item.key"
          class="sidebar-nav-item"
          type="button"
          :class="{ active: activeView === item.key }"
          :disabled="!item.enabled"
          :title="item.label"
          @click="navigateTo(item)"
        >
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <section class="conversation-section">
        <header class="conversation-section-header">
          <span>对话历史</span>
          <ChevronDown :size="14" />
        </header>
        <p v-if="conversationStore.error" class="conversation-error">
          {{ conversationStore.error }}
        </p>
        <div class="conversation-list">
          <div
            v-for="conversation in conversationStore.conversations"
            :key="conversation.id"
            class="conversation-row"
            :class="{ active: conversation.id === conversationStore.activeId }"
          >
            <button
              class="conversation-item"
              type="button"
              @click="openConversation(conversation.id)"
            >
              <span>{{ conversation.title }}</span>
            </button>
            <button
              class="conversation-more"
              type="button"
              title="更多"
              @click.stop="toggleMenu(conversation.id)"
            >
              <MoreHorizontal :size="18" />
            </button>
            <div v-if="openMenuId === conversation.id" class="conversation-menu">
              <button type="button" @click="handleRename(conversation)">重命名</button>
              <button type="button" class="danger" @click="requestDelete(conversation)">删除</button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <nav v-else class="collapsed-sidebar-nav" aria-label="折叠主导航">
      <button
        v-for="item in navigationItems"
        :key="item.key"
        class="collapsed-sidebar-nav-item"
        type="button"
        :class="{ active: activeView === item.key }"
        :disabled="!item.enabled"
        :title="item.label"
        :aria-label="item.label"
        @click="navigateTo(item)"
      >
        <component :is="item.icon" :size="19" />
      </button>
    </nav>

    <div v-if="pendingDelete" class="modal-backdrop" @click.self="pendingDelete = null">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <h2 id="delete-title">删除对话？</h2>
        <p>删除后，该对话将从历史列表中移除。</p>
        <div class="confirm-actions">
          <button type="button" class="secondary-button" @click="pendingDelete = null">取消</button>
          <button type="button" class="danger-button" @click="confirmDelete">删除</button>
        </div>
      </section>
    </div>
  </aside>
</template>
