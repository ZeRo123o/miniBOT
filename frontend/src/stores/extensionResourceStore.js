import { reactive } from 'vue'
import { listResources, listSkills } from '../apis/resources'

const CACHE_TTL_MS = 30_000
const resourceKinds = ['tool', 'mcp', 'skill']

export const extensionResourceStore = reactive({
  resourcesByKind: {
    tool: [],
    mcp: [],
    skill: [],
  },
  loading: false,
  refreshing: false,
  loadedAt: 0,
  error: '',
})

let loadingPromise = null

function normalizeResource(kind, resource) {
  return {
    ...resource,
    kind,
    enabled: kind === 'skill' ? true : resource.enabled,
  }
}

function hasCachedData() {
  return extensionResourceStore.loadedAt > 0
}

function isFresh() {
  return Date.now() - extensionResourceStore.loadedAt < CACHE_TTL_MS
}

export async function loadExtensionResources({ force = false } = {}) {
  if (!force && hasCachedData() && isFresh()) return
  if (loadingPromise) return loadingPromise

  const canRenderCachedData = hasCachedData()
  extensionResourceStore.loading = !canRenderCachedData
  extensionResourceStore.refreshing = canRenderCachedData
  extensionResourceStore.error = ''

  loadingPromise = Promise.all(
    resourceKinds.map((kind) => (kind === 'skill' ? listSkills() : listResources(kind))),
  )
    .then((results) => {
      resourceKinds.forEach((kind, index) => {
        extensionResourceStore.resourcesByKind[kind] = results[index].map((resource) =>
          normalizeResource(kind, resource),
        )
      })
      extensionResourceStore.loadedAt = Date.now()
    })
    .catch((error) => {
      extensionResourceStore.error = error.message
    })
    .finally(() => {
      extensionResourceStore.loading = false
      extensionResourceStore.refreshing = false
      loadingPromise = null
    })

  return loadingPromise
}

export function updateCachedExtensionResource(kind, resource) {
  const resources = extensionResourceStore.resourcesByKind[kind] || []
  const key = kind === 'skill' ? 'slug' : 'name'
  const index = resources.findIndex((item) => item[key] === resource[key])
  if (index !== -1) {
    resources[index] = normalizeResource(kind, resource)
  }
}
