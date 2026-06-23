<script setup>
import { computed, ref } from 'vue'
import { ChevronDown, ChevronRight, Wrench } from 'lucide-vue-next'
import ToolCallRenderer from './ToolCallRenderer.vue'

const props = defineProps({
  toolCalls: { type: Array, default: () => [] },
  isActive: { type: Boolean, default: false },
})

const expanded = ref(false)
const normalized = computed(() => props.toolCalls.filter((toolCall) => toolCall?.id && toolCall.tool_name))
const finished = computed(() => normalized.value.filter((item) => item.status === 'finished').length)
const failed = computed(() => normalized.value.filter((item) => item.status === 'failed').length)
const title = computed(() => normalized.value.length === 1
  ? `使用了工具：${normalized.value[0].tool_name.replaceAll('_', ' ')}`
  : `已调用 ${normalized.value.length} 个工具`)
const status = computed(() => {
  if (failed.value) return `${failed.value} 失败`
  if (finished.value === normalized.value.length) return '已完成'
  return '进行中'
})

</script>

<template>
  <section v-if="normalized.length" class="tool-calls-group">
    <button type="button" class="tool-calls-summary" :aria-expanded="expanded" @click="expanded = !expanded">
      <Wrench :size="15" />
      <span class="summary-title">{{ title }}</span>
      <span class="summary-status">{{ status }}</span>
      <ChevronDown v-if="expanded" :size="15" />
      <ChevronRight v-else :size="15" />
    </button>
    <div v-if="expanded" class="tool-calls-panel">
      <ToolCallRenderer v-for="toolCall in normalized" :key="toolCall.id" :tool-call="toolCall" />
    </div>
  </section>
</template>

<style scoped>
.tool-calls-group { margin-top: 8px; }
.tool-calls-summary { display: inline-flex; max-width: 100%; align-items: center; gap: 8px; padding: 5px 8px; border: 0; border-radius: 6px; background: #f8fafc; color: #64748b; font-size: 13px; cursor: pointer; }
.tool-calls-summary:hover { background: #f1f5f9; color: #334155; }
.summary-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.summary-status { padding: 1px 5px; border-radius: 4px; background: #eef2f7; font-size: 11px; white-space: nowrap; }
.tool-calls-panel { margin: 5px 0 8px 16px; padding: 3px 0 3px 12px; border-left: 1px solid #e2e8f0; }
</style>
