<script setup>
import { Check, ChevronDown } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, ref, useId } from 'vue'

const props = defineProps({
  modelValue: {
    type: [String, Number],
    default: '',
  },
  options: {
    type: Array,
    default: () => [],
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  ariaLabel: {
    type: String,
    required: true,
  },
  menuWidth: {
    type: Number,
    default: null,
  },
  menuAlign: {
    type: String,
    default: 'start',
    validator: (value) => ['start', 'end'].includes(value),
  },
})

const emit = defineEmits(['update:modelValue'])

const triggerRef = ref(null)
const menuRef = ref(null)
const open = ref(false)
const activeIndex = ref(-1)
const menuStyle = ref({})
const listboxId = useId()

const selectedIndex = computed(() =>
  props.options.findIndex((option) => option.value === props.modelValue),
)
const selectedOption = computed(() => props.options[selectedIndex.value])
const selectedLabel = computed(() =>
  selectedOption.value?.selectedLabel || selectedOption.value?.label || '',
)
const selectedTitle = computed(() => selectedOption.value?.label || selectedLabel.value)

function positionMenu() {
  if (!triggerRef.value) return
  const rect = triggerRef.value.getBoundingClientRect()
  const gap = 6
  const availableBelow = window.innerHeight - rect.bottom - gap - 8
  const menuHeight = Math.min(props.options.length, 5) * 40 + 8
  const openAbove = availableBelow < menuHeight && rect.top > availableBelow
  const width = props.menuWidth || rect.width
  const preferredLeft = props.menuAlign === 'end' ? rect.right - width : rect.left
  const maxLeft = Math.max(8, window.innerWidth - width - 8)
  const left = Math.min(Math.max(preferredLeft, 8), maxLeft)

  // Teleport 到 body 后使用 fixed 定位，避免被知识库面板的 overflow 裁切。
  menuStyle.value = {
    left: `${left}px`,
    top: openAbove ? 'auto' : `${rect.bottom + gap}px`,
    bottom: openAbove ? `${window.innerHeight - rect.top + gap}px` : 'auto',
    width: `${width}px`,
  }
}

async function showMenu() {
  if (props.disabled) return
  open.value = true
  activeIndex.value = selectedIndex.value >= 0 ? selectedIndex.value : 0
  positionMenu()
  window.addEventListener('resize', positionMenu)
  window.addEventListener('scroll', positionMenu, true)
  document.addEventListener('pointerdown', handleOutsidePointerDown)
  await nextTick()
  scrollActiveOptionIntoView()
}

function closeMenu({ restoreFocus = false } = {}) {
  if (!open.value) return
  open.value = false
  window.removeEventListener('resize', positionMenu)
  window.removeEventListener('scroll', positionMenu, true)
  document.removeEventListener('pointerdown', handleOutsidePointerDown)
  if (restoreFocus) triggerRef.value?.focus()
}

function toggleMenu() {
  if (open.value) closeMenu()
  else showMenu()
}

function handleOutsidePointerDown(event) {
  if (triggerRef.value?.contains(event.target) || menuRef.value?.contains(event.target)) return
  closeMenu()
}

function selectOption(option) {
  emit('update:modelValue', option.value)
  closeMenu({ restoreFocus: true })
}

function scrollActiveOptionIntoView() {
  menuRef.value
    ?.querySelector(`[data-option-index="${activeIndex.value}"]`)
    ?.scrollIntoView({ block: 'nearest' })
}

async function moveActive(step) {
  if (!props.options.length) return
  activeIndex.value = (activeIndex.value + step + props.options.length) % props.options.length
  await nextTick()
  scrollActiveOptionIntoView()
}

function handleTriggerKeydown(event) {
  if (props.disabled) return
  if (!open.value && ['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
    event.preventDefault()
    showMenu()
    return
  }
  handleMenuKeydown(event)
}

function handleMenuKeydown(event) {
  if (!open.value) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    moveActive(event.key === 'ArrowDown' ? 1 : -1)
  } else if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    activeIndex.value = event.key === 'Home' ? 0 : props.options.length - 1
    nextTick(scrollActiveOptionIntoView)
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    const option = props.options[activeIndex.value]
    if (option) selectOption(option)
  } else if (event.key === 'Escape' || event.key === 'Tab') {
    closeMenu({ restoreFocus: event.key === 'Escape' })
  }
}

onBeforeUnmount(() => closeMenu())
</script>

<template>
  <div class="app-select">
    <button
      ref="triggerRef"
      type="button"
      class="app-select-trigger"
      :class="{ open }"
      :disabled="disabled"
      :aria-label="ariaLabel"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-controls="listboxId"
      @click="toggleMenu"
      @keydown="handleTriggerKeydown"
    >
      <span :title="selectedTitle">{{ selectedLabel }}</span>
      <ChevronDown class="app-select-chevron" :size="16" aria-hidden="true" />
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        :id="listboxId"
        ref="menuRef"
        class="app-select-menu"
        role="listbox"
        :aria-label="ariaLabel"
        :style="menuStyle"
        tabindex="-1"
        @keydown="handleMenuKeydown"
      >
        <button
          v-for="(option, index) in options"
          :key="option.value"
          type="button"
          class="app-select-option"
          :class="{ active: index === activeIndex, selected: option.value === modelValue }"
          role="option"
          :aria-selected="option.value === modelValue"
          :data-option-index="index"
          @mouseenter="activeIndex = index"
          @click="selectOption(option)"
        >
          <span :title="option.label">{{ option.label }}</span>
          <Check v-if="option.value === modelValue" :size="16" aria-hidden="true" />
        </button>
      </div>
    </Teleport>
  </div>
</template>
