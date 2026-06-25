<script setup>
defineProps({
  url: {
    type: String,
    required: true,
  },
})
</script>

<template>
  <figure class="chart-result">
    <img :src="url" alt="生成的图表" />
  </figure>
</template>

<style scoped>
.chart-result {
  display: flex;
  width: 100%;
  margin: 8px 0 0;
  justify-content: center;
}

.chart-result img {
  display: block;
  width: auto;
  max-width: min(100%, 720px);
  max-height: 480px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  object-fit: contain;
}
</style>
