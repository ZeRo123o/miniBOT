<script setup>
import { computed, ref } from 'vue'
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  LoaderCircle,
  Search,
  Wrench,
} from 'lucide-vue-next'
import ChartToolResult from './ChartToolResult.vue'

const props = defineProps({
  toolCall: { type: Object, required: true },
})

const expanded = ref(false)
const isTask = computed(() => props.toolCall.tool_name === 'task')
const isFinished = computed(() => props.toolCall.status === 'finished')
const isFailed = computed(() => props.toolCall.status === 'failed')
const statusText = computed(() => (isFinished.value ? '已完成' : isFailed.value ? '失败' : '进行中'))
const label = computed(() => {
  const names = {
    tavily_search: 'Tavily search',
    query_kb: '知识库检索',
    list_kbs: '查看知识库',
    task: '子任务',
    sandbox_read_file: '读取文件',
    sandbox_write_file: '写入文件',
    sandbox_ls: '查看目录',
    sandbox_glob: '查找文件',
    sandbox_grep: '搜索文本',
  }
  return names[props.toolCall.tool_name] || props.toolCall.tool_name || '工具调用'
})
const detail = computed(() => {
  const args = props.toolCall.args || {}
  return args.query || args.description || args.path || props.toolCall.activity?.detail || ''
})
const childTools = computed(() => props.toolCall.child_tool_calls || [])
const subagents = computed(() => Object.values(props.toolCall.subagents || {}))
const hasDetails = computed(() => Boolean(
  detail.value || childTools.value.length || subagents.value.length || props.toolCall.error,
))

function toggle() {
  if (hasDetails.value) expanded.value = !expanded.value
}
</script>

<template>
  <div class="tool-call" :class="{ 'is-task': isTask }">
    <button type="button" class="tool-header" :aria-expanded="expanded" @click="toggle">
      <Search v-if="toolCall.tool_name === 'tavily_search'" :size="16" class="tool-icon" />
      <Wrench v-else-if="isTask" :size="16" class="tool-icon" />
      <CheckCircle2 v-else-if="isFinished" :size="16" class="tool-icon success" />
      <CircleAlert v-else-if="isFailed" :size="16" class="tool-icon error" />
      <LoaderCircle v-else :size="16" class="tool-icon spinning" />
      <span class="tool-header-content">
        <span class="tool-title">{{ isTask ? label : `${label}` }}</span>
        <span v-if="detail" class="tool-separator">｜</span>
        <span v-if="detail" class="tool-detail">{{ detail }}</span>
      </span>
      <span class="tool-status">{{ statusText }}</span>
      <ChevronDown v-if="expanded" :size="15" class="tool-chevron" />
      <ChevronRight v-else-if="hasDetails" :size="15" class="tool-chevron" />
    </button>

    <div v-if="expanded" class="tool-panel">
      <p v-if="toolCall.error" class="tool-error">{{ toolCall.error }}</p>
      <template v-if="isTask">
        <section v-for="subagent in subagents" :key="subagent.childThreadId" class="subagent-run">
          <header>子任务 · {{ subagent.type }} · {{ subagent.status }}</header>
          <ToolCallRenderer
            v-for="child in subagent.toolCalls || []"
            :key="child.id"
            :tool-call="child"
          />
          <pre v-if="subagent.text" class="subagent-output">{{ subagent.text }}</pre>
          <p v-if="subagent.error" class="tool-error">{{ subagent.error }}</p>
        </section>
        <ToolCallRenderer
          v-for="child in childTools"
          :key="child.id"
          :tool-call="child"
        />
      </template>
      <pre v-else-if="detail" class="tool-args">{{ detail }}</pre>
      <ChartToolResult v-if="toolCall.chart_url" :url="toolCall.chart_url" />
    </div>
    <ChartToolResult v-else-if="toolCall.chart_url" :url="toolCall.chart_url" />
  </div>
</template>

<style scoped>
.tool-call { margin: 0; color: #64748b; }
.tool-header { display: flex; width: 100%; min-width: 0; align-items: center; gap: 8px; padding: 5px 0; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.tool-header:hover { color: #334155; }
.tool-icon { flex: 0 0 auto; color: #94a3b8; }
.tool-icon.success { color: #22a06b; }
.tool-icon.error { color: #dc2626; }
.spinning { animation: spin 1.15s linear infinite; color: #0ea5e9; }
.tool-header-content { display: flex; min-width: 0; flex: 1; align-items: center; gap: 7px; font-size: 13px; }
.tool-title { flex: 0 0 auto; font-weight: 500; }
.tool-separator { color: #cbd5e1; }
.tool-detail { overflow: hidden; color: #94a3b8; text-overflow: ellipsis; white-space: nowrap; }
.tool-status { flex: 0 0 auto; padding: 1px 5px; border-radius: 4px; background: #f1f5f9; font-size: 11px; color: #64748b; }
.tool-chevron { flex: 0 0 auto; color: #cbd5e1; }
.tool-panel { margin: 2px 0 7px 8px; padding: 3px 0 3px 12px; border-left: 1px solid #e2e8f0; }
.tool-args, .subagent-output { max-height: 240px; margin: 3px 0; overflow: auto; white-space: pre-wrap; word-break: break-word; font: inherit; font-size: 12px; line-height: 1.6; color: #64748b; }
.subagent-run { padding: 3px 0 5px; }
.subagent-run > header { margin-bottom: 2px; font-size: 12px; color: #64748b; }
.tool-error { margin: 3px 0; color: #dc2626; font-size: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
