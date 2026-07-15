<script setup>
import { Box } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

const props = defineProps({
  providerId: {
    type: String,
    default: '',
  },
  size: {
    type: Number,
    default: 20,
  },
})

const ICON_BASE = 'https://registry.npmmirror.com/@lobehub/icons-static-svg/latest/files/icons'

// Provider ID 是稳定运行时标识；别名在这里显式归并，避免误用显示名称或协议类型猜测厂商。
const providerIconFiles = {
  alibaba: 'bailian-color.svg',
  dashscope: 'bailian-color.svg',
  openai: 'openai.svg',
  deepseek: 'deepseek-color.svg',
  minimax: 'minimax-color.svg',
  'minimax-cn': 'minimax-color.svg',
  modelscope: 'modelscope-color.svg',
  siliconflow: 'siliconcloud-color.svg',
  'siliconflow-cn': 'siliconcloud-color.svg',
  xiaomi: 'xiaomimimo.svg',
  'xiaomi-token-plan-cn': 'xiaomimimo.svg',
}

const loadFailed = ref(false)
const normalizedProviderId = computed(() => props.providerId.trim().toLowerCase())
const iconUrl = computed(() => {
  const filename = providerIconFiles[normalizedProviderId.value]
  return filename ? `${ICON_BASE}/${filename}` : ''
})

// Provider 切换后允许重新加载新图标；单个远程资源失败时只影响当前实例。
watch(normalizedProviderId, () => {
  loadFailed.value = false
})
</script>

<template>
  <img
    v-if="iconUrl && !loadFailed"
    class="provider-brand-icon"
    :src="iconUrl"
    :width="size"
    :height="size"
    alt=""
    aria-hidden="true"
    decoding="async"
    referrerpolicy="no-referrer"
    @error="loadFailed = true"
  />
  <Box v-else :size="size" aria-hidden="true" />
</template>
