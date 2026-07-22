<script setup>
import {
  BarChart3,
  Blocks,
  BookOpenText,
  Box,
  BriefcaseBusiness,
  Building2,
  Check,
  ChevronDown,
  Github,
  IdCard,
  EllipsisVertical,
  LogOut,
  Mail,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Phone,
  PlusCircle,
  RefreshCw,
  Save,
  Search,
  Settings,
  SquarePen,
  Trash2,
  Upload,
  UserRound,
  UsersRound,
  X,
} from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  createUser,
  createWorkspace,
  deleteUser,
  deleteWorkspace,
  listUsers,
  listWorkspaces,
  updateUser,
  updateWorkspace,
} from '../apis/auth'
import {
  conversationStore,
  newConversation,
  removeConversation,
  renameConversation,
  selectConversation,
} from '../stores/conversationStore'
import { authStore, changeMyPassword, logout, saveMyAvatar, saveMyProfile } from '../stores/authStore'
import { selectionStore } from '../stores/selectionStore'
import defaultUserAvatar from '../assets/default-user-avatar.png'
import AppSelect from './AppSelect.vue'

defineProps({
  collapsed: {
    type: Boolean,
    default: false,
  },
  activeView: {
    type: String,
    default: 'chat',
  },
})

const emit = defineEmits(['navigate', 'toggle'])

const openMenuId = ref(null)
const userMenuOpen = ref(false)
const systemSettingsOpen = ref(false)
const activeSettingsTab = ref('account')
const pendingDelete = ref(null)
const profileSaving = ref(false)
const passwordSaving = ref(false)
const profileMessage = ref('')
const profileError = ref('')
const passwordMessage = ref('')
const passwordError = ref('')
const editingProfileField = ref('')
const departmentsLoading = ref(false)
const departmentsSaving = ref(false)
const departmentToast = ref(null)
const workspaces = ref([])
const editingWorkspaceId = ref(null)
const departmentEditorOpen = ref(false)
const departmentSearchQuery = ref('')
const openDepartmentMenuId = ref(null)
const departmentMenuPosition = reactive({ top: 0, left: 0 })
const pendingWorkspaceDelete = ref(null)
const departmentDeleting = ref(false)
const users = ref([])
const usersLoading = ref(false)
const usersSaving = ref(false)
const userDeleting = ref(false)
const userSearchQuery = ref('')
const userWorkspaceFilter = ref('')
const userRoleFilter = ref('')
const openUserRowMenuId = ref(null)
const userMenuPosition = reactive({ top: 0, left: 0 })
const userEditorOpen = ref(false)
const editingUserId = ref(null)
const pendingUserDelete = ref(null)
const avatarInputRef = ref(null)
const avatarUploading = ref(false)
let departmentToastTimer = null
const profileForm = reactive({
  username: '',
  phone: '',
  email: '',
})
const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})
const workspaceForm = reactive({
  name: '',
  description: '',
  adminUid: '',
  adminPassword: '',
})
const userForm = reactive({
  uid: '',
  username: '',
  email: '',
  password: '',
  role: 'user',
  workspaceId: '',
})

const currentUser = computed(() => authStore.user || {})
const displayName = computed(() => currentUser.value.username || currentUser.value.uid || '未命名用户')
const displayUid = computed(() => currentUser.value.uid || selectionStore.userId)
const workspaceName = computed(() => currentUser.value.workspace_name || '未分配部门')
const roleLabel = computed(() => {
  const labels = {
    superadmin: '超级管理员',
    admin: '管理员',
    user: '普通用户',
  }
  return labels[currentUser.value.role] || currentUser.value.role || '未知角色'
})
const roleBadgeClass = computed(() => {
  const role = currentUser.value.role || 'user'
  return `role-badge-${role}`
})
const avatarSrc = computed(() => currentUser.value.avatar_url || defaultUserAvatar)

const navigationItems = [
  { key: 'chat', label: '工作区', icon: BriefcaseBusiness, enabled: true },
  { key: 'knowledge', label: '知识库', icon: BookOpenText, enabled: true },
  { key: 'extensions', label: '扩展管理', icon: Blocks, enabled: true },
  { key: 'models', label: '模型配置', icon: Box, enabled: true, roles: ['admin', 'superadmin'] },
  { key: 'dashboard', label: 'Dashboard', icon: BarChart3, enabled: false, roles: ['superadmin'] },
]

const visibleNavigationItems = computed(() => {
  const role = currentUser.value.role || 'user'
  return navigationItems.filter((item) => !item.roles || item.roles.includes(role))
})

const settingsNavItems = computed(() => {
  const items = [{ key: 'account', label: '账户设置', icon: UserRound }]
  if (currentUser.value.role === 'superadmin') {
    items.push({ key: 'departments', label: '部门管理', icon: Building2 })
    items.push({ key: 'users', label: '用户管理', icon: UsersRound })
  } else if (currentUser.value.role === 'admin') {
    items.push({ key: 'users', label: '用户管理', icon: UsersRound })
  }
  return items
})

const activeSettingsItem = computed(() => {
  return settingsNavItems.value.find((item) => item.key === activeSettingsTab.value) || settingsNavItems.value[0]
})

const profileDirty = computed(() => {
  return (
    profileForm.username.trim() !== (currentUser.value.username || '') ||
    profileForm.phone.trim() !== (currentUser.value.phone || '') ||
    profileForm.email.trim() !== (currentUser.value.email || '')
  )
})

const accountInfoItems = computed(() => [
  { key: 'uid', label: '账号 ID', value: currentUser.value.uid || '-', icon: IdCard },
  { key: 'username', label: '用户名', value: profileForm.username || '-', icon: UserRound, editable: true },
  { key: 'phone', label: '手机号', value: profileForm.phone || '未填写', icon: Phone, editable: true },
  { key: 'workspace', label: '部门', value: workspaceName.value, icon: Building2 },
  { key: 'email', label: '邮箱', value: profileForm.email || '未填写', icon: Mail, editable: true, wide: true },
])

const filteredWorkspaces = computed(() => {
  const query = departmentSearchQuery.value.trim().toLocaleLowerCase('zh-CN')
  if (!query) return workspaces.value
  return workspaces.value.filter((workspace) => {
    const admins = (workspace.admins || []).map((admin) => admin.username || admin.uid).join(' ')
    return `${workspace.name} ${workspace.description || ''} ${admins}`.toLocaleLowerCase('zh-CN').includes(query)
  })
})
const activeDepartmentMenuWorkspace = computed(() => {
  return workspaces.value.find((workspace) => workspace.id === openDepartmentMenuId.value) || null
})
const userWorkspaceOptions = computed(() => {
  if (currentUser.value.role === 'superadmin') return workspaces.value
  if (!currentUser.value.workspace_id) return []
  return [{ id: currentUser.value.workspace_id, name: workspaceName.value }]
})
const filteredUsers = computed(() => {
  const query = userSearchQuery.value.trim().toLocaleLowerCase('zh-CN')
  return users.value.filter((user) => {
    const matchesQuery =
      !query || `${user.username || ''} ${user.uid || ''}`.toLocaleLowerCase('zh-CN').includes(query)
    const matchesWorkspace =
      !userWorkspaceFilter.value || String(user.workspace_id || '') === userWorkspaceFilter.value
    const matchesRole = !userRoleFilter.value || user.role === userRoleFilter.value
    return matchesQuery && matchesWorkspace && matchesRole
  })
})
const activeUserRowMenuUser = computed(() => {
  return users.value.find((user) => user.id === openUserRowMenuId.value) || null
})
const editingUser = computed(() => {
  return users.value.find((user) => user.id === editingUserId.value) || null
})
const userWorkspaceFilterOptions = computed(() => [
  { value: '', label: '全部部门' },
  ...userWorkspaceOptions.value.map((workspace) => ({
    value: String(workspace.id),
    label: workspace.name,
  })),
])
const userRoleFilterOptions = computed(() => [
  { value: '', label: '全部角色' },
  ...(currentUser.value.role === 'superadmin'
    ? [{ value: 'superadmin', label: '超级管理员' }]
    : []),
  { value: 'admin', label: '管理员' },
  { value: 'user', label: '普通用户' },
])
const userEditorWorkspaceOptions = computed(() =>
  userWorkspaceOptions.value.map((workspace) => ({
    value: String(workspace.id),
    label: workspace.name,
  })),
)
const userEditorRoleOptions = computed(() => {
  if (editingUser.value?.role === 'superadmin') {
    return [{ value: 'superadmin', label: '超级管理员' }]
  }
  if (currentUser.value.role === 'superadmin') {
    return [
      { value: 'admin', label: '管理员' },
      { value: 'user', label: '普通用户' },
    ]
  }
  return [{ value: 'user', label: '普通用户' }]
})

function formatDateTime(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatUserDate(value) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(value))
}

function userRoleLabel(role) {
  return {
    superadmin: '超级管理员',
    admin: '管理员',
    user: '普通用户',
  }[role] || role || '未知角色'
}

function canManageUser(user) {
  if (currentUser.value.role === 'superadmin') return true
  return user.role === 'user' && user.workspace_id === currentUser.value.workspace_id
}

function navigateTo(item) {
  if (!item.enabled) return
  emit('navigate', item.key)
}

function toggleMenu(conversationId) {
  userMenuOpen.value = false
  openMenuId.value = openMenuId.value === conversationId ? null : conversationId
}

function closeMenusOnOutsideClick(event) {
  if (openMenuId.value && !event.target.closest('.conversation-more, .conversation-menu')) {
    openMenuId.value = null
  }
  if (userMenuOpen.value && !event.target.closest('.sidebar-user-area')) {
    userMenuOpen.value = false
  }
  if (
    openDepartmentMenuId.value &&
    !event.target.closest('.department-row-actions, .department-row-menu')
  ) {
    openDepartmentMenuId.value = null
  }
  if (
    openUserRowMenuId.value &&
    !event.target.closest('.user-row-actions, .user-row-menu')
  ) {
    openUserRowMenuId.value = null
  }
  if (
    editingProfileField.value &&
    !event.target.closest('.account-inline-edit, .account-field-edit-button')
  ) {
    editingProfileField.value = ''
  }
}

function toggleUserMenu() {
  openMenuId.value = null
  userMenuOpen.value = !userMenuOpen.value
}

function handleSystemSettings() {
  userMenuOpen.value = false
  activeSettingsTab.value = settingsNavItems.value[0]?.key || 'account'
  resetAccountForms()
  systemSettingsOpen.value = true
}

function closeSystemSettings() {
  openDepartmentMenuId.value = null
  openUserRowMenuId.value = null
  pendingWorkspaceDelete.value = null
  pendingUserDelete.value = null
  userEditorOpen.value = false
  systemSettingsOpen.value = false
}

function selectSettingsTab(key) {
  openDepartmentMenuId.value = null
  openUserRowMenuId.value = null
  activeSettingsTab.value = key
  if (key === 'departments') {
    loadDepartmentManagement()
  } else if (key === 'users') {
    loadUserManagement()
  }
}

function resetAccountForms() {
  profileForm.username = currentUser.value.username || ''
  profileForm.phone = currentUser.value.phone || ''
  profileForm.email = currentUser.value.email || ''
  editingProfileField.value = ''
  passwordForm.old_password = ''
  passwordForm.new_password = ''
  passwordForm.confirm_password = ''
  profileMessage.value = ''
  profileError.value = ''
  passwordMessage.value = ''
  passwordError.value = ''
}

async function submitProfile() {
  profileSaving.value = true
  profileMessage.value = ''
  profileError.value = ''
  try {
    await saveMyProfile({
      username: profileForm.username.trim(),
      phone: profileForm.phone.trim(),
      email: profileForm.email.trim(),
    })
    profileMessage.value = '资料已更新'
    editingProfileField.value = ''
  } catch (error) {
    profileError.value = error.message
  } finally {
    profileSaving.value = false
  }
}

async function editProfileField(key) {
  editingProfileField.value = key
  profileMessage.value = ''
  profileError.value = ''
  await nextTick()
  document.querySelector(`[data-profile-field="${key}"] input`)?.focus()
}

function chooseAvatar() {
  if (avatarUploading.value) return
  avatarInputRef.value?.click()
}

async function handleAvatarFileChange(event) {
  const [file] = Array.from(event.target.files || [])
  event.target.value = ''
  if (!file || !file.type.startsWith('image/')) return
  avatarUploading.value = true
  profileError.value = ''
  profileMessage.value = ''
  try {
    await saveMyAvatar(file)
    profileMessage.value = '头像已更新'
  } catch (error) {
    profileError.value = error.message
  } finally {
    avatarUploading.value = false
  }
}

async function submitPassword() {
  passwordSaving.value = true
  passwordMessage.value = ''
  passwordError.value = ''
  if (passwordForm.new_password.length < 8) {
    passwordError.value = '新密码至少需要 8 位'
    passwordSaving.value = false
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    passwordError.value = '两次输入的新密码不一致'
    passwordSaving.value = false
    return
  }
  try {
    await changeMyPassword({ ...passwordForm })
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm_password = ''
    passwordMessage.value = '密码已更新'
  } catch (error) {
    passwordError.value = error.message
  } finally {
    passwordSaving.value = false
  }
}

function resetWorkspaceForm() {
  editingWorkspaceId.value = null
  workspaceForm.name = ''
  workspaceForm.description = ''
  workspaceForm.adminUid = ''
  workspaceForm.adminPassword = ''
}

function showDepartmentToast(message, type = 'success') {
  window.clearTimeout(departmentToastTimer)
  departmentToast.value = {
    id: Date.now(),
    message,
    type,
  }
  departmentToastTimer = window.setTimeout(() => {
    departmentToast.value = null
  }, type === 'error' ? 3000 : 2000)
}

function openCreateWorkspace() {
  resetWorkspaceForm()
  departmentEditorOpen.value = true
}

function closeWorkspaceEditor() {
  departmentEditorOpen.value = false
  resetWorkspaceForm()
}

function replaceWorkspace(updatedWorkspace) {
  const index = workspaces.value.findIndex((workspace) => workspace.id === updatedWorkspace.id)
  if (index >= 0) {
    workspaces.value.splice(index, 1, updatedWorkspace)
  } else {
    workspaces.value.push(updatedWorkspace)
  }
}

async function loadDepartmentManagement() {
  if (currentUser.value.role !== 'superadmin') return
  departmentsLoading.value = true
  try {
    workspaces.value = await listWorkspaces()
    openDepartmentMenuId.value = null
  } catch (error) {
    showDepartmentToast(error.message, 'error')
  } finally {
    departmentsLoading.value = false
  }
}

function startEditWorkspace(workspace) {
  openDepartmentMenuId.value = null
  editingWorkspaceId.value = workspace.id
  workspaceForm.name = workspace.name
  workspaceForm.description = workspace.description || ''
  departmentEditorOpen.value = true
}

async function submitWorkspace() {
  departmentsSaving.value = true
  try {
    const payload = {
      name: workspaceForm.name.trim(),
      description: workspaceForm.description.trim(),
    }
    if (!editingWorkspaceId.value) {
      payload.admin_uid = workspaceForm.adminUid.trim()
      payload.admin_password = workspaceForm.adminPassword
    }
    const workspace = editingWorkspaceId.value
      ? await updateWorkspace(editingWorkspaceId.value, payload)
      : await createWorkspace(payload)
    replaceWorkspace(workspace)
    showDepartmentToast(editingWorkspaceId.value ? '部门已更新' : '部门已创建')
    closeWorkspaceEditor()
  } catch (error) {
    showDepartmentToast(error.message, 'error')
  } finally {
    departmentsSaving.value = false
  }
}

function toggleDepartmentMenu(workspace, event) {
  if (openDepartmentMenuId.value === workspace.id) {
    openDepartmentMenuId.value = null
    return
  }
  const triggerRect = event.currentTarget.getBoundingClientRect()
  departmentMenuPosition.top = triggerRect.bottom + 6
  departmentMenuPosition.left = Math.max(12, triggerRect.right - 132)
  openDepartmentMenuId.value = workspace.id
}

function requestWorkspaceDelete(workspace) {
  openDepartmentMenuId.value = null
  pendingWorkspaceDelete.value = workspace
}

function editActiveDepartment() {
  const workspace = activeDepartmentMenuWorkspace.value
  if (workspace) startEditWorkspace(workspace)
}

function deleteActiveDepartment() {
  const workspace = activeDepartmentMenuWorkspace.value
  if (workspace) requestWorkspaceDelete(workspace)
}

async function confirmWorkspaceDelete() {
  if (!pendingWorkspaceDelete.value) return
  const workspace = pendingWorkspaceDelete.value
  departmentDeleting.value = true
  try {
    await deleteWorkspace(workspace.id)
    workspaces.value = workspaces.value.filter((item) => item.id !== workspace.id)
    pendingWorkspaceDelete.value = null
    showDepartmentToast(`部门“${workspace.name}”已删除`)
  } catch (error) {
    pendingWorkspaceDelete.value = null
    showDepartmentToast(error.message, 'error')
  } finally {
    departmentDeleting.value = false
  }
}

function resetUserForm() {
  editingUserId.value = null
  userForm.uid = ''
  userForm.username = ''
  userForm.email = ''
  userForm.password = ''
  userForm.role = 'user'
  userForm.workspaceId = String(currentUser.value.workspace_id || userWorkspaceOptions.value[0]?.id || '')
}

async function loadUserManagement() {
  if (!['superadmin', 'admin'].includes(currentUser.value.role)) return
  usersLoading.value = true
  try {
    if (currentUser.value.role === 'superadmin') {
      const [loadedUsers, loadedWorkspaces] = await Promise.all([listUsers(), listWorkspaces()])
      users.value = loadedUsers
      workspaces.value = loadedWorkspaces
    } else {
      users.value = await listUsers()
    }
    openUserRowMenuId.value = null
  } catch (error) {
    showDepartmentToast(error.message, 'error')
  } finally {
    usersLoading.value = false
  }
}

function openCreateUser() {
  resetUserForm()
  userEditorOpen.value = true
}

function closeUserEditor() {
  userEditorOpen.value = false
  resetUserForm()
}

function startEditUser(user) {
  openUserRowMenuId.value = null
  editingUserId.value = user.id
  userForm.uid = user.uid
  userForm.username = user.username || ''
  userForm.email = user.email || ''
  userForm.password = ''
  userForm.role = user.role
  userForm.workspaceId = String(user.workspace_id || '')
  userEditorOpen.value = true
}

function replaceUser(updatedUser) {
  const index = users.value.findIndex((user) => user.id === updatedUser.id)
  if (index >= 0) {
    users.value.splice(index, 1, updatedUser)
  } else {
    users.value.push(updatedUser)
  }
  if (updatedUser.id === currentUser.value.id) {
    authStore.user = { ...authStore.user, ...updatedUser }
  }
}

async function submitUser() {
  usersSaving.value = true
  try {
    const payload = {
      username: userForm.username.trim(),
      email: userForm.email.trim(),
      role: userForm.role,
      workspace_id: userForm.workspaceId ? Number(userForm.workspaceId) : null,
    }
    const updatedUser = editingUserId.value
      ? await updateUser(editingUserId.value, payload)
      : await createUser({
          ...payload,
          uid: userForm.uid.trim(),
          password: userForm.password,
        })
    replaceUser(updatedUser)
    showDepartmentToast(editingUserId.value ? '用户信息已更新' : '用户已创建')
    closeUserEditor()
  } catch (error) {
    showDepartmentToast(error.message, 'error')
  } finally {
    usersSaving.value = false
  }
}

function toggleUserRowMenu(user, event) {
  if (openUserRowMenuId.value === user.id) {
    openUserRowMenuId.value = null
    return
  }
  openDepartmentMenuId.value = null
  const triggerRect = event.currentTarget.getBoundingClientRect()
  const menuHeight = 88
  userMenuPosition.top =
    triggerRect.bottom + menuHeight + 12 > window.innerHeight
      ? Math.max(12, triggerRect.top - menuHeight - 6)
      : triggerRect.bottom + 6
  userMenuPosition.left = Math.max(12, triggerRect.right - 132)
  openUserRowMenuId.value = user.id
}

function editActiveUser() {
  const user = activeUserRowMenuUser.value
  if (user) startEditUser(user)
}

function requestUserDelete(user) {
  openUserRowMenuId.value = null
  pendingUserDelete.value = user
}

function deleteActiveUser() {
  const user = activeUserRowMenuUser.value
  if (user) requestUserDelete(user)
}

async function confirmUserDelete() {
  if (!pendingUserDelete.value) return
  const user = pendingUserDelete.value
  userDeleting.value = true
  try {
    await deleteUser(user.id)
    users.value = users.value.filter((item) => item.id !== user.id)
    pendingUserDelete.value = null
    showDepartmentToast(`用户“${user.username || user.uid}”已删除`)
  } catch (error) {
    pendingUserDelete.value = null
    showDepartmentToast(error.message, 'error')
  } finally {
    userDeleting.value = false
  }
}

function handleLogout() {
  userMenuOpen.value = false
  logout()
}

function handleGlobalKeydown(event) {
  if (event.key === 'Escape') {
    openMenuId.value = null
    openDepartmentMenuId.value = null
    openUserRowMenuId.value = null
    userMenuOpen.value = false
    if (pendingUserDelete.value) {
      pendingUserDelete.value = null
      return
    }
    if (userEditorOpen.value) {
      closeUserEditor()
      return
    }
    if (pendingWorkspaceDelete.value) {
      pendingWorkspaceDelete.value = null
      return
    }
    if (departmentEditorOpen.value) {
      closeWorkspaceEditor()
      return
    }
    systemSettingsOpen.value = false
    pendingDelete.value = null
  }
}

async function handleRename(conversation) {
  openMenuId.value = null
  const title = window.prompt('重命名对话', conversation.title)
  if (title === null || title.trim() === conversation.title) return
  await renameConversation(conversation.id, selectionStore.userId, title)
}

function requestDelete(conversation) {
  openMenuId.value = null
  pendingDelete.value = conversation
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  const conversationId = pendingDelete.value.id
  pendingDelete.value = null
  await removeConversation(conversationId, selectionStore.userId)
}

function startNewConversation() {
  newConversation()
  emit('navigate', 'chat')
}

async function openConversation(conversationId) {
  emit('navigate', 'chat')
  await selectConversation(conversationId, selectionStore.userId)
}

onMounted(() => {
  document.addEventListener('pointerdown', closeMenusOnOutsideClick)
  document.addEventListener('keydown', handleGlobalKeydown)
})
onBeforeUnmount(() => {
  window.clearTimeout(departmentToastTimer)
  document.removeEventListener('pointerdown', closeMenusOnOutsideClick)
  document.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<template>
  <aside class="conversation-sidebar" :class="{ collapsed }">
    <header class="conversation-sidebar-header">
      <h1 v-if="!collapsed">MiniBOT</h1>
      <button
        class="sidebar-toggle"
        type="button"
        :title="collapsed ? '展开侧边栏' : '折叠侧边栏'"
        @click="$emit('toggle')"
      >
        <PanelLeftOpen v-if="collapsed" :size="18" />
        <PanelLeftClose v-else :size="18" />
      </button>
    </header>

    <div v-if="!collapsed" class="conversation-sidebar-body">
      <button
        class="new-chat-button"
        type="button"
        :disabled="conversationStore.loading"
        @click="startNewConversation"
      >
        <SquarePen :size="18" />
        <span>创建新对话</span>
      </button>

      <nav class="sidebar-nav" aria-label="主导航">
        <button
          v-for="item in visibleNavigationItems"
          :key="item.key"
          class="sidebar-nav-item"
          type="button"
          :class="{ active: activeView === item.key }"
          :disabled="!item.enabled"
          :title="item.label"
          @click="navigateTo(item)"
        >
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <section class="conversation-section">
        <header class="conversation-section-header">
          <span>对话历史</span>
          <ChevronDown :size="14" />
        </header>
        <p v-if="conversationStore.error" class="conversation-error">
          {{ conversationStore.error }}
        </p>
        <div class="conversation-list">
          <div
            v-for="conversation in conversationStore.conversations"
            :key="conversation.id"
            class="conversation-row"
            :class="{ active: conversation.id === conversationStore.activeId }"
          >
            <button
              class="conversation-item"
              type="button"
              @click="openConversation(conversation.id)"
            >
              <span>{{ conversation.title }}</span>
            </button>
            <button
              class="conversation-more"
              type="button"
              title="更多"
              @click.stop="toggleMenu(conversation.id)"
            >
              <MoreHorizontal :size="18" />
            </button>
            <div v-if="openMenuId === conversation.id" class="conversation-menu">
              <button type="button" @click="handleRename(conversation)">重命名</button>
              <button type="button" class="danger" @click="requestDelete(conversation)">删除</button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <nav v-if="collapsed" class="collapsed-sidebar-nav" aria-label="折叠主导航">
      <button
        v-for="item in visibleNavigationItems"
        :key="item.key"
        class="collapsed-sidebar-nav-item"
        type="button"
        :class="{ active: activeView === item.key }"
        :disabled="!item.enabled"
        :title="item.label"
        :aria-label="item.label"
        @click="navigateTo(item)"
      >
        <component :is="item.icon" :size="19" />
      </button>
    </nav>

    <div class="sidebar-user-area" :class="{ collapsed }">
      <a
        class="sidebar-github-link"
        href="https://github.com/ZeRo123o/miniBOT"
        target="_blank"
        rel="noreferrer"
        title="GitHub"
        aria-label="GitHub"
      >
        <Github :size="collapsed ? 19 : 18" />
        <span v-if="!collapsed">GitHub</span>
      </a>
      <div v-if="userMenuOpen" class="sidebar-user-menu">
        <div class="sidebar-user-menu-profile">
          <span class="sidebar-user-avatar">
            <img :src="avatarSrc" alt="" />
          </span>
          <span class="sidebar-user-menu-meta">
            <strong>{{ displayName }}</strong>
            <span>{{ workspaceName }}</span>
          </span>
        </div>
        <button type="button" @click="handleSystemSettings">
          <Settings :size="16" />
          <span>系统设置</span>
        </button>
        <button type="button" class="danger" @click="handleLogout">
          <LogOut :size="16" />
          <span>退出登录</span>
        </button>
      </div>
      <button
        class="sidebar-user-button"
        type="button"
        :title="`${displayName} · ${displayUid}`"
        @click="toggleUserMenu"
      >
        <span class="sidebar-user-avatar">
          <img :src="avatarSrc" alt="" />
        </span>
        <span v-if="!collapsed" class="sidebar-user-meta">
          <strong>{{ displayName }}</strong>
        </span>
      </button>
    </div>

    <div v-if="systemSettingsOpen" class="modal-backdrop settings-modal-backdrop">
      <section class="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <aside class="settings-dialog-sidebar" aria-label="系统设置导航">
          <header class="settings-dialog-profile">
            <span class="sidebar-user-avatar">
              <img :src="avatarSrc" alt="" />
            </span>
            <span>
              <strong>{{ displayName }}</strong>
              <small class="role-badge" :class="roleBadgeClass">{{ roleLabel }}</small>
            </span>
          </header>
          <nav class="settings-dialog-nav">
            <button
              v-for="item in settingsNavItems"
              :key="item.key"
              type="button"
              :class="{ active: activeSettingsTab === item.key }"
              @click="selectSettingsTab(item.key)"
            >
              <component :is="item.icon" :size="17" />
              <span>{{ item.label }}</span>
            </button>
          </nav>
        </aside>

        <div class="settings-dialog-main">
          <header class="settings-dialog-header">
            <div>
              <h2 id="settings-title">系统设置</h2>
              <p>{{ workspaceName }}</p>
            </div>
            <button class="settings-dialog-close" type="button" title="关闭" @click="closeSystemSettings">
              <X :size="18" />
            </button>
          </header>
          <section v-if="activeSettingsTab === 'account'" class="account-settings-panel">
            <form class="settings-section account-info-section" @submit.prevent="submitProfile">
              <header class="account-info-header">
                <div>
                  <h3>基本信息</h3>
                  <p>当前账号的身份与归属信息。</p>
                </div>
                <button
                  type="submit"
                  class="account-save-button"
                  :disabled="profileSaving || !profileDirty || !profileForm.username.trim()"
                >
                  <Save :size="15" />
                  <span>{{ profileSaving ? '保存中...' : '保存' }}</span>
                </button>
              </header>
              <div class="account-info-layout">
                <div class="account-avatar-panel">
                  <div class="account-avatar-large">
                    <img class="account-avatar-image" :src="avatarSrc" alt="" />
                  </div>
                  <button
                    type="button"
                    class="account-avatar-button"
                    :disabled="avatarUploading"
                    @click="chooseAvatar"
                  >
                    <Upload :size="15" />
                    <span>{{ avatarUploading ? '上传中...' : '更换头像' }}</span>
                  </button>
                  <input
                    ref="avatarInputRef"
                    class="account-avatar-input"
                    type="file"
                    accept="image/*"
                    @change="handleAvatarFileChange"
                  />
                </div>
                <dl class="account-info-grid">
                  <div
                    v-for="item in accountInfoItems"
                    :key="item.key"
                    :data-profile-field="item.key"
                    :class="[{ editable: item.editable, wide: item.wide }, `account-info-item-${item.key}`]"
                  >
                    <component :is="item.icon" class="account-info-icon" :size="24" />
                    <div class="account-info-content">
                      <dt>{{ item.label }}</dt>
                      <dd v-if="editingProfileField !== item.key">
                        <span>{{ item.value }}</span>
                        <button
                          v-if="item.editable"
                          type="button"
                          class="account-field-edit-button"
                          @click="editProfileField(item.key)"
                        >
                          <Pencil :size="15" />
                        </button>
                      </dd>
                      <dd v-else class="account-inline-edit">
                        <input
                          v-if="item.key === 'username'"
                          v-model="profileForm.username"
                          type="text"
                          autocomplete="name"
                        />
                        <input
                          v-else-if="item.key === 'phone'"
                          v-model="profileForm.phone"
                          type="tel"
                          autocomplete="tel"
                          placeholder="未填写"
                        />
                        <input
                          v-else-if="item.key === 'email'"
                          v-model="profileForm.email"
                          type="email"
                          autocomplete="email"
                          placeholder="未填写"
                        />
                      </dd>
                    </div>
                  </div>
                </dl>
              </div>
              <p v-if="profileError" class="settings-form-message error">{{ profileError }}</p>
              <p v-else-if="profileMessage" class="settings-form-message success">{{ profileMessage }}</p>
            </form>

            <form class="settings-section settings-form" @submit.prevent="submitPassword">
              <header>
                <h3>修改密码</h3>
                <p>修改后请使用新密码登录。</p>
              </header>
              <label>
                <span>旧密码</span>
                <input v-model="passwordForm.old_password" type="password" autocomplete="current-password" />
              </label>
              <label>
                <span>新密码</span>
                <input v-model="passwordForm.new_password" type="password" autocomplete="new-password" />
              </label>
              <label>
                <span>确认密码</span>
                <input v-model="passwordForm.confirm_password" type="password" autocomplete="new-password" />
              </label>
              <p v-if="passwordError" class="settings-form-message error">{{ passwordError }}</p>
              <p v-else-if="passwordMessage" class="settings-form-message success">{{ passwordMessage }}</p>
              <div class="settings-form-actions">
                <button
                  type="submit"
                  :disabled="
                    passwordSaving ||
                    !passwordForm.old_password ||
                    !passwordForm.new_password ||
                    !passwordForm.confirm_password
                  "
                >
                  {{ passwordSaving ? '保存中...' : '修改密码' }}
                </button>
              </div>
            </form>
          </section>

          <section
            v-else-if="activeSettingsTab === 'departments'"
            class="department-settings-panel"
            @scroll.passive="openDepartmentMenuId = null"
          >
            <section class="department-toolbar-card">
              <div>
                <h3>部门列表</h3>
                <p>共 {{ workspaces.length }} 个部门</p>
              </div>
              <div class="department-toolbar-actions">
                <label class="department-search-box">
                  <Search :size="17" />
                  <input v-model="departmentSearchQuery" type="search" placeholder="搜索部门名称或管理员" />
                </label>
                <button
                  type="button"
                  class="department-refresh-button"
                  :disabled="departmentsLoading"
                  @click="loadDepartmentManagement"
                >
                  <RefreshCw :size="18" />
                  <span>{{ departmentsLoading ? '刷新中' : '刷新' }}</span>
                </button>
                <button type="button" class="department-create-button" @click="openCreateWorkspace">
                  <PlusCircle :size="18" />
                  <span>新建部门</span>
                </button>
              </div>
            </section>

            <p v-if="departmentsLoading" class="department-empty">正在加载部门...</p>
            <p v-else-if="!workspaces.length" class="department-empty">暂无部门，先创建一个部门。</p>
            <p v-else-if="!filteredWorkspaces.length" class="department-empty">没有找到匹配的部门。</p>

            <div v-else class="department-table-shell">
              <table class="department-table">
                <thead>
                  <tr>
                    <th>部门名称</th>
                    <th>管理员</th>
                    <th>人数</th>
                    <th>创建时间</th>
                    <th class="department-operation-column">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="workspace in filteredWorkspaces" :key="workspace.id">
                    <td>
                      <div class="department-name-cell">
                        <strong>{{ workspace.name }}</strong>
                        <span>{{ workspace.description || '暂无描述' }}</span>
                      </div>
                    </td>
                    <td>
                      <span class="department-admin-cell">
                        {{
                          workspace.admins?.length
                            ? workspace.admins.map((admin) => admin.username || admin.uid).join('、')
                            : '未设置'
                        }}
                      </span>
                    </td>
                    <td>{{ workspace.user_count }}</td>
                    <td>{{ formatDateTime(workspace.created_at) }}</td>
                    <td class="department-operation-column">
                      <div class="department-row-actions">
                        <button
                          type="button"
                          class="department-more-button"
                          :aria-expanded="openDepartmentMenuId === workspace.id"
                          :aria-label="`${workspace.name}操作`"
                          @click.stop="toggleDepartmentMenu(workspace, $event)"
                        >
                          <EllipsisVertical :size="20" />
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <Teleport to="body">
              <div
                v-if="activeDepartmentMenuWorkspace"
                class="department-row-menu department-row-menu-floating"
                :style="{
                  top: `${departmentMenuPosition.top}px`,
                  left: `${departmentMenuPosition.left}px`,
                }"
              >
                <button type="button" @click="editActiveDepartment">
                  <Pencil :size="16" />
                  <span>编辑</span>
                </button>
                <button type="button" class="danger" @click="deleteActiveDepartment">
                  <Trash2 :size="16" />
                  <span>删除</span>
                </button>
              </div>
            </Teleport>

            <div v-if="departmentEditorOpen" class="department-editor-layer">
              <form class="department-editor-card" @submit.prevent="submitWorkspace">
                <header>
                  <h3>{{ editingWorkspaceId ? '编辑部门' : '新建部门' }}</h3>
                  <button type="button" aria-label="关闭" @click="closeWorkspaceEditor">
                    <X :size="20" />
                  </button>
                </header>
                <label>
                  <span>部门名称</span>
                  <input v-model="workspaceForm.name" type="text" placeholder="例如：计算机与软件学院" />
                </label>
                <label>
                  <span>部门描述（选填）</span>
                  <textarea
                    v-model="workspaceForm.description"
                    maxlength="200"
                    rows="5"
                    placeholder="描述该部门负责的团队或工作区范围"
                  />
                  <small>{{ workspaceForm.description.length }}/200</small>
                </label>
                <label v-if="!editingWorkspaceId">
                  <span>管理员账户 ID</span>
                  <input v-model="workspaceForm.adminUid" type="text" placeholder="例如：admin-cs" />
                </label>
                <label v-if="!editingWorkspaceId">
                  <span>管理员密码</span>
                  <input
                    v-model="workspaceForm.adminPassword"
                    type="password"
                    autocomplete="new-password"
                    placeholder="至少 8 位"
                  />
                </label>
                <div class="department-editor-actions">
                  <button type="button" class="department-editor-cancel" @click="closeWorkspaceEditor">取消</button>
                  <button
                    type="submit"
                    :disabled="
                      departmentsSaving ||
                      !workspaceForm.name.trim() ||
                      (!editingWorkspaceId && (!workspaceForm.adminUid.trim() || workspaceForm.adminPassword.length < 8))
                    "
                  >
                    {{ departmentsSaving ? '保存中' : editingWorkspaceId ? '保存' : '创建' }}
                  </button>
                </div>
              </form>
            </div>
          </section>
          <section
            v-else-if="activeSettingsTab === 'users'"
            class="department-settings-panel user-settings-panel"
            @scroll.passive="openUserRowMenuId = null"
          >
            <section class="department-toolbar-card user-toolbar-card">
              <div class="user-toolbar-heading">
                <h3>用户列表</h3>
                <p>共 {{ users.length }} 个用户</p>
              </div>
              <div class="department-toolbar-actions user-toolbar-actions">
                <label class="department-search-box user-search-box">
                  <Search :size="17" />
                  <input v-model="userSearchQuery" type="search" placeholder="搜索用户名或账户 ID" />
                </label>
                <AppSelect
                  v-model="userWorkspaceFilter"
                  class="user-filter-select"
                  aria-label="按部门筛选"
                  :options="userWorkspaceFilterOptions"
                  :menu-width="180"
                />
                <AppSelect
                  v-model="userRoleFilter"
                  class="user-filter-select"
                  aria-label="按角色筛选"
                  :options="userRoleFilterOptions"
                  :menu-width="140"
                />
                <button
                  type="button"
                  class="department-refresh-button user-refresh-button"
                  :disabled="usersLoading"
                  @click="loadUserManagement"
                >
                  <RefreshCw :size="18" />
                  <span>{{ usersLoading ? '刷新中' : '刷新' }}</span>
                </button>
                <button
                  type="button"
                  class="department-create-button user-create-button"
                  :disabled="usersLoading || !userWorkspaceOptions.length"
                  @click="openCreateUser"
                >
                  <PlusCircle :size="18" />
                  <span>新建用户</span>
                </button>
              </div>
            </section>

            <p v-if="usersLoading" class="department-empty">正在加载用户...</p>
            <p v-else-if="!users.length" class="department-empty">暂无用户，先创建一个用户。</p>
            <p v-else-if="!filteredUsers.length" class="department-empty">没有找到匹配的用户。</p>

            <template v-else>
              <div class="department-table-shell user-table-shell">
                <table class="user-table">
                  <thead>
                    <tr>
                      <th>用户</th>
                      <th>所属部门</th>
                      <th>角色</th>
                      <th>创建时间</th>
                      <th class="department-operation-column">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="user in filteredUsers" :key="user.id">
                      <td>
                        <div class="user-identity-cell">
                          <img :src="user.avatar_url || defaultUserAvatar" :alt="`${user.username || user.uid}头像`" />
                          <span class="user-identity-copy">
                            <strong>{{ user.username || user.uid }}</strong>
                            <small>ID: {{ user.uid }}</small>
                          </span>
                        </div>
                      </td>
                      <td><span class="user-workspace-name">{{ user.workspace_name || '未分配部门' }}</span></td>
                      <td>
                        <span class="user-role-tag" :class="`role-${user.role}`">
                          {{ userRoleLabel(user.role) }}
                        </span>
                      </td>
                      <td>{{ formatUserDate(user.created_at) }}</td>
                      <td class="department-operation-column">
                        <div v-if="canManageUser(user)" class="department-row-actions user-row-actions">
                          <button
                            type="button"
                            class="department-more-button"
                            :aria-expanded="openUserRowMenuId === user.id"
                            :aria-label="`${user.username || user.uid}操作`"
                            @click.stop="toggleUserRowMenu(user, $event)"
                          >
                            <EllipsisVertical :size="20" />
                          </button>
                        </div>
                        <span v-else class="user-operation-unavailable">-</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p class="user-table-summary">已显示 {{ filteredUsers.length }} / {{ users.length }}</p>
            </template>

            <Teleport to="body">
              <div
                v-if="activeUserRowMenuUser"
                class="department-row-menu department-row-menu-floating user-row-menu"
                :style="{
                  top: `${userMenuPosition.top}px`,
                  left: `${userMenuPosition.left}px`,
                }"
              >
                <button type="button" @click="editActiveUser">
                  <Pencil :size="16" />
                  <span>编辑</span>
                </button>
                <button
                  type="button"
                  class="danger"
                  :disabled="activeUserRowMenuUser.id === currentUser.id || activeUserRowMenuUser.role === 'superadmin'"
                  :title="
                    activeUserRowMenuUser.id === currentUser.id
                      ? '不能删除当前登录账户'
                      : activeUserRowMenuUser.role === 'superadmin'
                        ? '不能删除超级管理员账户'
                        : '删除用户'
                  "
                  @click="deleteActiveUser"
                >
                  <Trash2 :size="16" />
                  <span>删除</span>
                </button>
              </div>
            </Teleport>

            <div v-if="userEditorOpen" class="department-editor-layer">
              <form class="department-editor-card user-editor-card" @submit.prevent="submitUser">
                <header>
                  <h3>{{ editingUserId ? '编辑用户' : '新建用户' }}</h3>
                  <button type="button" aria-label="关闭" @click="closeUserEditor">
                    <X :size="20" />
                  </button>
                </header>
                <label>
                  <span>账户 ID</span>
                  <input
                    v-model="userForm.uid"
                    type="text"
                    :readonly="Boolean(editingUserId)"
                    placeholder="例如：student-01"
                    autocomplete="username"
                  />
                </label>
                <label>
                  <span>用户名</span>
                  <input v-model="userForm.username" type="text" placeholder="请输入用户名" />
                </label>
                <label>
                  <span>邮箱（选填）</span>
                  <input v-model="userForm.email" type="email" placeholder="name@example.com" />
                </label>
                <label v-if="!editingUserId">
                  <span>初始密码</span>
                  <input
                    v-model="userForm.password"
                    type="password"
                    autocomplete="new-password"
                    placeholder="至少 8 位"
                  />
                </label>
                <div class="user-editor-field">
                  <span>所属部门</span>
                  <AppSelect
                    v-model="userForm.workspaceId"
                    class="user-editor-app-select"
                    aria-label="所属部门"
                    :options="userEditorWorkspaceOptions"
                    :disabled="currentUser.role !== 'superadmin' || editingUser?.role === 'superadmin'"
                  />
                </div>
                <div class="user-editor-field">
                  <span>角色</span>
                  <AppSelect
                    v-model="userForm.role"
                    class="user-editor-app-select"
                    aria-label="角色"
                    :options="userEditorRoleOptions"
                    :disabled="currentUser.role !== 'superadmin' || editingUser?.role === 'superadmin'"
                  />
                </div>
                <div class="department-editor-actions">
                  <button type="button" class="department-editor-cancel" @click="closeUserEditor">取消</button>
                  <button
                    type="submit"
                    :disabled="
                      usersSaving ||
                      !userForm.uid.trim() ||
                      !userForm.username.trim() ||
                      !userForm.workspaceId ||
                      (!editingUserId && userForm.password.length < 8)
                    "
                  >
                    {{ usersSaving ? '保存中' : editingUserId ? '保存' : '创建' }}
                  </button>
                </div>
              </form>
            </div>
          </section>
          <section v-else class="settings-dialog-placeholder">
            <component :is="activeSettingsItem.icon" :size="28" />
            <h3>{{ activeSettingsItem.label }}</h3>
            <p>该栏目内容稍后接入。</p>
          </section>
        </div>
      </section>
    </div>

    <Teleport to="body">
      <Transition name="department-toast">
        <div
          v-if="departmentToast"
          :key="departmentToast.id"
          class="department-toast-stack"
          :role="departmentToast.type === 'error' ? 'alert' : 'status'"
          aria-live="polite"
        >
          <p class="department-toast-message">
            <span class="department-toast-icon" :class="departmentToast.type">
              <Check v-if="departmentToast.type === 'success'" :size="12" />
              <X v-else :size="12" />
            </span>
            <span>{{ departmentToast.message }}</span>
          </p>
        </div>
      </Transition>
    </Teleport>

    <div
      v-if="pendingWorkspaceDelete"
      class="modal-backdrop"
      @click.self="pendingWorkspaceDelete = null"
    >
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="workspace-delete-title">
        <h2 id="workspace-delete-title">删除部门？</h2>
        <p>
          将删除“{{ pendingWorkspaceDelete.name }}”，并停用该部门下的所有账户。此操作无法撤销。
        </p>
        <div class="confirm-actions">
          <button type="button" class="secondary-button" :disabled="departmentDeleting" @click="pendingWorkspaceDelete = null">
            取消
          </button>
          <button type="button" class="danger-button" :disabled="departmentDeleting" @click="confirmWorkspaceDelete">
            {{ departmentDeleting ? '删除中...' : '删除' }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="pendingUserDelete" class="modal-backdrop" @click.self="pendingUserDelete = null">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="user-delete-title">
        <h2 id="user-delete-title">删除用户？</h2>
        <p>
          将删除“{{ pendingUserDelete.username || pendingUserDelete.uid }}”的账户并停止其登录权限。此操作无法撤销。
        </p>
        <div class="confirm-actions">
          <button type="button" class="secondary-button" :disabled="userDeleting" @click="pendingUserDelete = null">
            取消
          </button>
          <button type="button" class="danger-button" :disabled="userDeleting" @click="confirmUserDelete">
            {{ userDeleting ? '删除中...' : '删除' }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="pendingDelete" class="modal-backdrop" @click.self="pendingDelete = null">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <h2 id="delete-title">删除对话？</h2>
        <p>删除后，该对话将从历史列表中移除。</p>
        <div class="confirm-actions">
          <button type="button" class="secondary-button" @click="pendingDelete = null">取消</button>
          <button type="button" class="danger-button" @click="confirmDelete">删除</button>
        </div>
      </section>
    </div>
  </aside>
</template>
