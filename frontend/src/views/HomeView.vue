<script setup>
import { onMounted } from 'vue'
import ChatBox from '../components/ChatBox.vue'
import ResourceSelector from '../components/ResourceSelector.vue'
import { loadWorkspace, persistSelection, selectionStore } from '../stores/selectionStore'

onMounted(loadWorkspace)
</script>

<template>
  <main class="page">
    <aside class="sidebar">
      <h1>miniBOT</h1>
      <p>FastAPI + LangChain + LangGraph + Vue 的插件化雏形。</p>
      <button class="primary" :disabled="selectionStore.loading" @click="persistSelection">
        保存选择
      </button>
      <p v-if="selectionStore.error" class="error">{{ selectionStore.error }}</p>
    </aside>

    <section class="workspace">
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
