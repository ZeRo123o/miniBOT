import { reactive } from 'vue'
import { getSelection, listKnowledgeBases, saveSelection } from '../apis/resources'

export const selectionStore = reactive({
  userKey: 'default',
  resources: {
    knowledgeBase: [],
  },
  selection: {
    user_key: 'default',
    knowledge_base_ids: [],
  },
  loading: false,
  hasUnsavedChanges: false,
  error: '',
})

export async function loadWorkspace() {
  selectionStore.loading = true
  selectionStore.error = ''
  try {
    const [knowledgeBases, selection] = await Promise.all([
      listKnowledgeBases(selectionStore.userKey),
      getSelection(selectionStore.userKey),
    ])
    selectionStore.resources.knowledgeBase = knowledgeBases
    selectionStore.selection = {
      user_key: selection.user_key || selectionStore.userKey,
      knowledge_base_ids: selection.knowledge_base_ids || [],
    }
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
  selectionStore.selection.user_key = selectionStore.userKey
  try {
    selectionStore.selection = await saveSelection(selectionStore.userKey, selectionStore.selection)
    selectionStore.hasUnsavedChanges = false
  } catch (error) {
    selectionStore.error = error.message
  } finally {
    selectionStore.loading = false
  }
}
