import { reactive } from 'vue'
import { getSelection, listKnowledgeBases, saveSelection } from '../apis/resources'

export const selectionStore = reactive({
  userId: 'default',
  resources: {
    knowledgeBase: [],
  },
  selection: {
    user_id: 'default',
    knowledge_base_ids: [],
  },
  savedKnowledgeBaseIds: [],
  loading: false,
  hasUnsavedChanges: false,
  error: '',
})

function normalizedKnowledgeBaseIds(ids) {
  return [...new Set(ids || [])].map(String).sort()
}

export function refreshSelectionDirtyState() {
  const currentIds = normalizedKnowledgeBaseIds(selectionStore.selection.knowledge_base_ids)
  const savedIds = normalizedKnowledgeBaseIds(selectionStore.savedKnowledgeBaseIds)
  selectionStore.hasUnsavedChanges =
    currentIds.length !== savedIds.length ||
    currentIds.some((id, index) => id !== savedIds[index])
}

export async function refreshKnowledgeBaseResources() {
  const knowledgeBases = await listKnowledgeBases(selectionStore.userId)
  selectionStore.resources.knowledgeBase = knowledgeBases
  return knowledgeBases
}

export function upsertKnowledgeBaseResource(knowledgeBase) {
  const currentItems = selectionStore.resources.knowledgeBase || []
  const existingIndex = currentItems.findIndex((item) => item.id === knowledgeBase.id)
  if (existingIndex < 0) {
    selectionStore.resources.knowledgeBase = [...currentItems, knowledgeBase]
    return
  }

  selectionStore.resources.knowledgeBase = currentItems.map((item, index) =>
    index === existingIndex ? knowledgeBase : item,
  )
}

export function removeKnowledgeBaseResource(knowledgeBaseId) {
  selectionStore.resources.knowledgeBase = selectionStore.resources.knowledgeBase.filter(
    (item) => item.id !== knowledgeBaseId,
  )
  selectionStore.selection.knowledge_base_ids = selectionStore.selection.knowledge_base_ids.filter(
    (item) => item !== knowledgeBaseId,
  )
  // 后端删除知识库时会同步清理已保存选择，本地基准也必须保持一致。
  selectionStore.savedKnowledgeBaseIds = selectionStore.savedKnowledgeBaseIds.filter(
    (item) => item !== knowledgeBaseId,
  )
  refreshSelectionDirtyState()
}

export async function loadWorkspace() {
  selectionStore.loading = true
  selectionStore.error = ''
  try {
    const [knowledgeBases, selection] = await Promise.all([
      listKnowledgeBases(selectionStore.userId),
      getSelection(selectionStore.userId),
    ])
    selectionStore.resources.knowledgeBase = knowledgeBases
    const selectedKnowledgeBaseIds = selection.knowledge_base_ids || []
    selectionStore.selection = {
      user_id: selection.user_id || selectionStore.userId,
      knowledge_base_ids: selectedKnowledgeBaseIds,
    }
    selectionStore.savedKnowledgeBaseIds = [...selectedKnowledgeBaseIds]
    selectionStore.hasUnsavedChanges = false
  } catch (error) {
    selectionStore.error = error.message
  } finally {
    selectionStore.loading = false
  }
}

export async function persistSelection() {
  if (!selectionStore.hasUnsavedChanges || selectionStore.loading) return

  selectionStore.loading = true
  selectionStore.error = ''
  selectionStore.selection.user_id = selectionStore.userId
  try {
    selectionStore.selection = await saveSelection(selectionStore.userId, selectionStore.selection)
    selectionStore.savedKnowledgeBaseIds = [
      ...(selectionStore.selection.knowledge_base_ids || []),
    ]
    selectionStore.hasUnsavedChanges = false
  } catch (error) {
    selectionStore.error = error.message
  } finally {
    selectionStore.loading = false
  }
}
