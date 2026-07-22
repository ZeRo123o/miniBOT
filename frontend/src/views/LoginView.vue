<script setup>
import { computed, reactive, ref } from 'vue'
import {
  Bot,
  BookOpenText,
  Database,
  Eye,
  FileText,
  LockKeyhole,
  Mail,
  Network,
  Phone,
  Search,
  ShieldCheck,
  UserRound,
  UsersRound,
  Workflow,
} from 'lucide-vue-next'
import { authStore, initializeFirstAdmin, signIn } from '../stores/authStore'

const form = reactive({
  uid: '',
  username: '',
  phone: '',
  email: '',
  password: '',
  workspaceName: '默认工作区',
})
const submitError = ref('')
const passwordVisible = ref(false)

const title = computed(() => (authStore.firstRun ? '初始化超级管理员' : '欢迎登录'))
const subtitle = computed(() =>
  authStore.firstRun
    ? '首次启动需要创建系统级账号，用于管理用户、工作区和全局配置'
    : '登录您的账户，继续使用 miniBOT 智能知识平台',
)
const submitText = computed(() => {
  if (authStore.loading) return '处理中...'
  return authStore.firstRun ? '创建并进入' : '登录'
})

async function submit() {
  submitError.value = ''
  try {
    if (authStore.firstRun) {
      await initializeFirstAdmin({
        uid: form.uid.trim(),
        username: form.username.trim() || form.uid.trim(),
        phone: form.phone.trim(),
        email: form.email.trim(),
        password: form.password,
        workspace_name: form.workspaceName.trim() || '默认工作区',
      })
    } else {
      await signIn({
        login_id: form.uid.trim(),
        password: form.password,
      })
    }
  } catch (error) {
    submitError.value = error.message
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-hero" aria-label="miniBOT 产品能力">
      <div class="auth-logo">
        <span class="auth-logo-mark">
          <Bot :size="22" />
        </span>
        <span>miniBOT</span>
      </div>

      <div class="auth-hero-copy">
        <h1>智能 <strong>Agent</strong> 知识库平台</h1>
        <p>连接知识、驱动协作，让 AI 工作流更高效</p>
      </div>

      <div class="auth-visual" aria-hidden="true">
        <div class="auth-orbit orbit-one"></div>
        <div class="auth-orbit orbit-two"></div>
        <div class="auth-orbit-node node-a"></div>
        <div class="auth-orbit-node node-b"></div>
        <div class="auth-orbit-node node-c"></div>
        <div class="auth-bot-stage">
          <div class="auth-bot-halo"></div>
          <div class="auth-bot">
            <Bot :size="42" />
          </div>
        </div>

        <article class="auth-capability-card card-search">
          <Search :size="34" />
          <div>
            <strong>搜索与检索</strong>
            <span></span>
            <span></span>
          </div>
        </article>
        <article class="auth-capability-card card-kb">
          <BookOpenText :size="34" />
          <div>
            <strong>知识管理</strong>
            <span></span>
            <span></span>
          </div>
        </article>
        <article class="auth-capability-card card-doc">
          <FileText :size="34" />
          <div>
            <strong>文档理解</strong>
            <span></span>
            <span></span>
          </div>
        </article>
        <article class="auth-capability-card card-share">
          <UsersRound :size="34" />
          <div>
            <strong>协作与分享</strong>
            <span></span>
            <span></span>
          </div>
        </article>
        <article class="auth-flow-card">
          <strong>工作流编排</strong>
          <Workflow :size="76" />
        </article>
      </div>

      <div class="auth-feature-row">
        <article>
          <Database :size="30" />
          <div>
            <strong>多源知识接入</strong>
            <p>支持文档、数据库、网页等多种数据源接入，统一管理与检索。</p>
          </div>
        </article>
        <article>
          <Network :size="30" />
          <div>
            <strong>Agent 工作流编排</strong>
            <p>可视化编排 AI Agent 工作流，连通工具与知识库，自动化完成任务。</p>
          </div>
        </article>
        <article>
          <ShieldCheck :size="30" />
          <div>
            <strong>企业级权限与安全</strong>
            <p>精细化权限控制与审计，保障数据安全合规，满足企业管理需求。</p>
          </div>
        </article>
      </div>
    </section>

    <section class="auth-form-pane">
      <form class="auth-card" @submit.prevent="submit">
        <div class="auth-card-brand">
          <span class="auth-logo-mark">
            <Bot :size="22" />
          </span>
          <strong>miniBOT</strong>
        </div>
        <h2>{{ title }}</h2>
        <p>{{ subtitle }}</p>

        <label class="auth-field">
          <span class="sr-only">账号 ID</span>
          <div class="auth-input-wrap">
            <UserRound :size="20" />
            <input v-model="form.uid" required autocomplete="username" placeholder="账号 / 邮箱" />
          </div>
        </label>

        <label v-if="authStore.firstRun" class="auth-field">
          <span class="sr-only">显示名称</span>
          <div class="auth-input-wrap">
            <UserRound :size="20" />
            <input v-model="form.username" autocomplete="name" placeholder="显示名称" />
          </div>
        </label>

        <label v-if="authStore.firstRun" class="auth-field">
          <span class="sr-only">电话</span>
          <div class="auth-input-wrap">
            <Phone :size="20" />
            <input v-model="form.phone" autocomplete="tel" type="tel" placeholder="电话" />
          </div>
        </label>

        <label v-if="authStore.firstRun" class="auth-field">
          <span class="sr-only">邮箱</span>
          <div class="auth-input-wrap">
            <Mail :size="20" />
            <input v-model="form.email" autocomplete="email" type="email" placeholder="邮箱" />
          </div>
        </label>

        <label v-if="authStore.firstRun" class="auth-field">
          <span class="sr-only">工作区名称</span>
          <div class="auth-input-wrap">
            <ShieldCheck :size="20" />
            <input v-model="form.workspaceName" required placeholder="工作区名称" />
          </div>
        </label>

        <label class="auth-field">
          <span class="sr-only">密码</span>
          <div class="auth-input-wrap">
            <LockKeyhole :size="20" />
            <input
              v-model="form.password"
              required
              :type="passwordVisible ? 'text' : 'password'"
              minlength="8"
              autocomplete="current-password"
              placeholder="密码"
            />
            <button
              class="auth-password-toggle"
              type="button"
              :aria-label="passwordVisible ? '隐藏密码' : '显示密码'"
              @click="passwordVisible = !passwordVisible"
            >
              <Eye :size="20" />
            </button>
          </div>
        </label>

        <p v-if="submitError || authStore.error" class="auth-error">
          {{ submitError || authStore.error }}
        </p>

        <button class="auth-submit" type="submit" :disabled="authStore.loading">
          {{ submitText }}
        </button>
      </form>
    </section>
  </main>
</template>
