import { reactive } from 'vue'
import { getSelection, listResources, saveSelection } from '../apis/resources'

export const selectionStore = reactive({
  userKey: 'default',
  resources: {
    mcp: [],
    skill: [],
    subagent: [],
  },
  selection: {
    user_key: 'default',
    mcps: [],
    skills: [],
    subagents: [],
  },
  loading: false,
  error: '',
})

export async function loadWorkspace() {
  selectionStore.loading = true
  selectionStore.error = ''
  try {
    const [mcps, skills, subagents, selection] = await Promise.all([
      listResources('mcp'),
      listResources('skill'),
      listResources('subagent'),
      getSelection(selectionStore.userKey),
    ])
    selectionStore.resources.mcp = mcps
    selectionStore.resources.skill = skills
    selectionStore.resources.subagent = subagents
    selectionStore.selection = selection
  } catch (error) {
    selectionStore.error = error.message
  } finally {
    selectionStore.loading = false
  }
}

export async function persistSelection() {
  selectionStore.selection.user_key = selectionStore.userKey
  selectionStore.selection = await saveSelection(selectionStore.userKey, selectionStore.selection)
}
