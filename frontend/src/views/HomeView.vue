<script setup>
import { onMounted, ref } from 'vue'
import ChatBox from '../components/ChatBox.vue'
import ConversationSidebar from '../components/ConversationSidebar.vue'
import WorkspaceSidebar from '../components/WorkspaceSidebar.vue'
import { loadConversations } from '../stores/conversationStore'
import { loadWorkspace, selectionStore } from '../stores/selectionStore'

const sidebarCollapsed = ref(false)
const workspaceCollapsed = ref(false)

onMounted(async () => {
  await Promise.all([
    loadWorkspace(),
    loadConversations(selectionStore.userKey),
  ])
})
</script>

<template>
  <main
    class="page"
    :class="{
      'sidebar-collapsed': sidebarCollapsed,
      'workspace-collapsed': workspaceCollapsed,
    }"
  >
    <ConversationSidebar
      :collapsed="sidebarCollapsed"
      @toggle="sidebarCollapsed = !sidebarCollapsed"
    />

    <section class="workspace">
      <ChatBox />
    </section>

    <WorkspaceSidebar
      :collapsed="workspaceCollapsed"
      @toggle="workspaceCollapsed = !workspaceCollapsed"
    />
  </main>
</template>
