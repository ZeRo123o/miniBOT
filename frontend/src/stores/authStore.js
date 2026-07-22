import { reactive } from 'vue'
import { getAuthToken, setAuthToken } from '../apis/base'
import {
  checkFirstRun,
  getMe,
  initializeAdmin,
  login,
  updateMyPassword,
  updateMyProfile,
  uploadMyAvatar,
} from '../apis/auth'
import { conversationStore } from './conversationStore'
import { selectionStore } from './selectionStore'

export const authStore = reactive({
  token: getAuthToken(),
  user: null,
  firstRun: false,
  loading: true,
  error: '',
})

function applyAuth(payload) {
  authStore.token = payload.access_token
  authStore.user = payload.user
  authStore.error = ''
  setAuthToken(payload.access_token)
  selectionStore.userId = payload.user.uid
  selectionStore.selection.user_id = payload.user.uid
}

export async function bootstrapAuth() {
  authStore.loading = true
  authStore.error = ''
  try {
    const firstRun = await checkFirstRun()
    authStore.firstRun = Boolean(firstRun.first_run)
    if (authStore.token && !authStore.firstRun) {
      const user = await getMe()
      authStore.user = user
      selectionStore.userId = user.uid
      selectionStore.selection.user_id = user.uid
    }
  } catch (error) {
    authStore.error = error.message
    logout()
  } finally {
    authStore.loading = false
  }
}

export async function initializeFirstAdmin(payload) {
  authStore.loading = true
  authStore.error = ''
  try {
    applyAuth(await initializeAdmin(payload))
    authStore.firstRun = false
  } catch (error) {
    authStore.error = error.message
    throw error
  } finally {
    authStore.loading = false
  }
}

export async function signIn(payload) {
  authStore.loading = true
  authStore.error = ''
  try {
    applyAuth(await login(payload))
  } catch (error) {
    authStore.error = error.message
    throw error
  } finally {
    authStore.loading = false
  }
}

export async function saveMyProfile(payload) {
  const user = await updateMyProfile(payload)
  authStore.user = user
  selectionStore.userId = user.uid
  selectionStore.selection.user_id = user.uid
  return user
}

export async function changeMyPassword(payload) {
  return updateMyPassword(payload)
}

export async function saveMyAvatar(file) {
  const user = await uploadMyAvatar(file)
  authStore.user = user
  return user
}

export function logout() {
  setAuthToken('')
  authStore.token = ''
  authStore.user = null
  selectionStore.userId = 'default'
  selectionStore.selection.user_id = 'default'
  conversationStore.conversations = []
  conversationStore.messagesByConversationId = {}
  conversationStore.runsByConversationId = {}
  conversationStore.activeId = null
}
