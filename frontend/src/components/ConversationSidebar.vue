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
import { ref } from 'vue'
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

function toggleMenu(conversationId) {
  openMenuId.value = openMenuId.value === conversationId ? null : conversationId
}

async function handleRename(conversation) {
  openMenuId.value = null
  const title = window.prompt('重命名对话', conversation.title)
  if (title === null || title.trim() === conversation.title) return
  await renameConversation(conversation.id, selectionStore.userKey, title)
}

function requestDelete(conversation) {
  openMenuId.value = null
  pendingDelete.value = conversation
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  const conversationId = pendingDelete.value.id
  pendingDelete.value = null
  await removeConversation(conversationId, selectionStore.userKey)
}

function startNewConversation() {
  newConversation()
  emit('navigate', 'chat')
}

async function openConversation(conversationId) {
  emit('navigate', 'chat')
  await selectConversation(conversationId, selectionStore.userKey)
}
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
          class="sidebar-nav-item"
          type="button"
          :class="{ active: activeView === 'chat' }"
          @click="emit('navigate', 'chat')"
        >
          <BriefcaseBusiness :size="18" />
          <span>工作区</span>
        </button>
        <button
          class="sidebar-nav-item"
          type="button"
          :class="{ active: activeView === 'knowledge' }"
          @click="emit('navigate', 'knowledge')"
        >
          <BookOpenText :size="18" />
          <span>知识库</span>
        </button>
        <button
          class="sidebar-nav-item"
          type="button"
          :class="{ active: activeView === 'extensions' }"
          @click="emit('navigate', 'extensions')"
        >
          <Blocks :size="18" />
          <span>扩展管理</span>
        </button>
        <button class="sidebar-nav-item" type="button">
          <Box :size="18" />
          <span>模型配置</span>
        </button>
        <button class="sidebar-nav-item" type="button">
          <BarChart3 :size="18" />
          <span>Dashboard</span>
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
