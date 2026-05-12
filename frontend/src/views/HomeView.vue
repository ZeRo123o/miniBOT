<script setup>
import { onMounted } from 'vue'
import ChatBox from '../components/ChatBox.vue'
import ConversationSidebar from '../components/ConversationSidebar.vue'
import ResourceSelector from '../components/ResourceSelector.vue'
import { loadConversations } from '../stores/conversationStore'
import { loadWorkspace, persistSelection, selectionStore } from '../stores/selectionStore'

onMounted(async () => {
  await Promise.all([
    loadWorkspace(),
    loadConversations(selectionStore.userKey),
  ])
})
</script>

<template>
  <main class="page">
    <ConversationSidebar />

    <section class="workspace">
      <header class="workspace-header">
        <div>
          <h1>miniBOT</h1>
          <p>选择资源后，可以在当前对话中运行测试。</p>
        </div>
        <button class="primary" :disabled="selectionStore.loading" @click="persistSelection">
          保存选择
        </button>
      </header>
      <p v-if="selectionStore.error" class="error">{{ selectionStore.error }}</p>

      <div class="grid">
        <ResourceSelector
          title="MCP"
          :items="selectionStore.resources.mcp"
          v-model="selectionStore.selection.mcps"
        />
        <ResourceSelector
          title="Skill"
          :items="selectionStore.resources.skill"
          v-model="selectionStore.selection.skills"
        />
        <ResourceSelector
          title="Subagent"
          :items="selectionStore.resources.subagent"
          v-model="selectionStore.selection.subagents"
        />
      </div>

      <ChatBox />
    </section>
  </main>
</template>
