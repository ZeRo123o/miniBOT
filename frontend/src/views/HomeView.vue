<script setup>
import { onMounted, reactive, ref } from 'vue'
import ChatBox from '../components/ChatBox.vue'
import ConversationSidebar from '../components/ConversationSidebar.vue'
import ExtensionManagementView from '../components/ExtensionManagementView.vue'
import KnowledgeBaseView from '../components/KnowledgeBaseView.vue'
import WorkspaceSidebar from '../components/WorkspaceSidebar.vue'
import { loadConversations } from '../stores/conversationStore'
import { loadWorkspace, selectionStore } from '../stores/selectionStore'

const sidebarCollapsed = ref(false)
const workspaceCollapsed = ref(false)
const navigationState = reactive({
  activeView: 'chat',
})

function setActiveView(view) {
  navigationState.activeView = view
}

onMounted(async () => {
  await Promise.all([
    loadWorkspace(),
    loadConversations(selectionStore.userId),
  ])
})
</script>

<template>
  <main
    class="page"
    :class="{
      'sidebar-collapsed': sidebarCollapsed,
      'workspace-collapsed': workspaceCollapsed,
      'knowledge-page-active': navigationState.activeView === 'knowledge',
      'extension-page-active': navigationState.activeView === 'extensions',
    }"
  >
    <ConversationSidebar
      :collapsed="sidebarCollapsed"
      :active-view="navigationState.activeView"
      @navigate="setActiveView"
      @toggle="sidebarCollapsed = !sidebarCollapsed"
    />

    <section class="workspace">
      <KnowledgeBaseView v-if="navigationState.activeView === 'knowledge'" />
      <ExtensionManagementView v-else-if="navigationState.activeView === 'extensions'" />
      <ChatBox v-else />
    </section>

    <WorkspaceSidebar
      v-if="navigationState.activeView === 'chat'"
      :collapsed="workspaceCollapsed"
      @toggle="workspaceCollapsed = !workspaceCollapsed"
    />
  </main>
</template>
