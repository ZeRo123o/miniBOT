<script setup>
import { onMounted } from 'vue'
import HomeView from './views/HomeView.vue'
import LoginView from './views/LoginView.vue'
import { authStore, bootstrapAuth } from './stores/authStore'

onMounted(() => {
  bootstrapAuth()
})
</script>

<template>
  <div v-if="authStore.loading && !authStore.user" class="auth-loading">
    正在检查登录状态...
  </div>
  <HomeView v-else-if="authStore.user" />
  <LoginView v-else />
</template>
