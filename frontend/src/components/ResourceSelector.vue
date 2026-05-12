<script setup>
const props = defineProps({
  title: { type: String, required: true },
  items: { type: Array, required: true },
  modelValue: { type: Array, required: true },
})

const emit = defineEmits(['update:modelValue'])

function toggle(name) {
  const selected = new Set(props.modelValue)
  if (selected.has(name)) selected.delete(name)
  else selected.add(name)
  emit('update:modelValue', Array.from(selected))
}
</script>

<template>
  <section class="panel">
    <header class="panel-header">
      <h2>{{ title }}</h2>
      <span>{{ modelValue.length }}/{{ items.length }}</span>
    </header>

    <div class="resource-list">
      <label v-for="item in items" :key="item.name" class="resource-row">
        <input
          type="checkbox"
          :checked="modelValue.includes(item.name)"
          @change="toggle(item.name)"
        />
        <span>
          <strong>{{ item.display_name }}</strong>
          <small>{{ item.name }}</small>
          <em>{{ item.description }}</em>
        </span>
      </label>
    </div>
  </section>
</template>
