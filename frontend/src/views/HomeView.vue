<script setup>
import { onMounted, reactive, ref } from 'vue'
import ChatBox from '../components/ChatBox.vue'
import ConversationSidebar from '../components/ConversationSidebar.vue'
import ExtensionManagementView from '../components/ExtensionManagementView.vue'
import KnowledgeBaseView from '../components/KnowledgeBaseView.vue'
import ModelProviderView from '../components/ModelProviderView.vue'
import WorkspaceSidebar from '../components/WorkspaceSidebar.vue'
import { loadConversations } from '../stores/conversationStore'
import { loadWorkspace, selectionStore } from '../stores/selectionStore'

const sidebarCollapsed = ref(false)
const workspaceCollapsed = ref(false)
const navigationState = reactive({
  activeView: 'chat',
})
const visitedViews = reactive({
  knowledge: false,
  extensions: false,
  models: false,
})

function setActiveView(view) {
  navigationState.activeView = view
  if (view in visitedViews) {
    visitedViews[view] = true
  }
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
      'model-page-active': navigationState.activeView === 'models',
    }"
  >
    <ConversationSidebar
      :collapsed="sidebarCollapsed"
      :active-view="navigationState.activeView"
      @navigate="setActiveView"
      @toggle="sidebarCollapsed = !sidebarCollapsed"
    />

    <section class="workspace">
      <KnowledgeBaseView
        v-if="visitedViews.knowledge"
        v-show="navigationState.activeView === 'knowledge'"
        :active="navigationState.activeView === 'knowledge'"
      />
      <ExtensionManagementView
        v-if="visitedViews.extensions"
        v-show="navigationState.activeView === 'extensions'"
      />
      <ModelProviderView
        v-if="visitedViews.models"
        v-show="navigationState.activeView === 'models'"
      />
      <ChatBox v-if="navigationState.activeView === 'chat'" />
    </section>

    <WorkspaceSidebar
      v-if="navigationState.activeView === 'chat'"
      :collapsed="workspaceCollapsed"
      @toggle="workspaceCollapsed = !workspaceCollapsed"
    />
  </main>
</template>
