import { reactive } from 'vue'
import { getSelection, listKnowledgeBases, listResources, saveSelection } from '../apis/resources'

export const selectionStore = reactive({
  userKey: 'default',
  resources: {
    mcp: [],
    skill: [],
    subagent: [],
    knowledgeBase: [],
  },
  selection: {
    user_key: 'default',
    mcps: [],
    skills: [],
    subagents: [],
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
    const [mcps, skills, subagents, knowledgeBases, selection] = await Promise.all([
      listResources('mcp'),
      listResources('skill'),
      listResources('subagent'),
      listKnowledgeBases(selectionStore.userKey),
      getSelection(selectionStore.userKey),
    ])
    selectionStore.resources.mcp = mcps
    selectionStore.resources.skill = skills
    selectionStore.resources.subagent = subagents
    selectionStore.resources.knowledgeBase = knowledgeBases
    selectionStore.selection = {
      ...selection,
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
