import { reactive } from 'vue'
import {
  listModelProviders,
  listModelUses,
  listModels,
} from '../apis/modelProviders'

const CACHE_TTL_MS = 30_000

export const modelProviderStore = reactive({
  providers: [],
  modelUses: [],
  chatModelsByProvider: {},
  loading: false,
  refreshing: false,
  loadedAt: 0,
  error: '',
})

let loadingPromise = null

function hasCachedData() {
  return modelProviderStore.loadedAt > 0
}

function isFresh() {
  return Date.now() - modelProviderStore.loadedAt < CACHE_TTL_MS
}

export async function loadModelProviderWorkspace({ force = false } = {}) {
  if (!force && hasCachedData() && isFresh()) return
  if (loadingPromise) return loadingPromise

  const canRenderCachedData = hasCachedData()
  modelProviderStore.loading = !canRenderCachedData
  modelProviderStore.refreshing = canRenderCachedData
  modelProviderStore.error = ''

  loadingPromise = Promise.all([
    listModelProviders(),
    listModelUses(),
    listModels('chat'),
  ])
    .then(([providers, modelUses, chatModelsByProvider]) => {
      modelProviderStore.providers = providers
      modelProviderStore.modelUses = modelUses
      modelProviderStore.chatModelsByProvider = chatModelsByProvider
      modelProviderStore.loadedAt = Date.now()
    })
    .catch((error) => {
      modelProviderStore.error = error.message
    })
    .finally(() => {
      modelProviderStore.loading = false
      modelProviderStore.refreshing = false
      loadingPromise = null
    })

  return loadingPromise
}

export function invalidateModelProviderWorkspace() {
  modelProviderStore.loadedAt = 0
}
