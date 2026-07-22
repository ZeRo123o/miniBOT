import { API_BASE, authHeaders, getResponseError, request } from './base'

export function checkFirstRun() {
  return request('/auth/check-first-run')
}

export function initializeAdmin(payload) {
  return request('/auth/initialize', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function login(payload) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getMe() {
  return request('/auth/me')
}

export function updateMyProfile(payload) {
  return request('/auth/me/profile', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function updateMyPassword(payload) {
  return request('/auth/me/password', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function uploadMyAvatar(file) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${API_BASE}/auth/me/avatar`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })
  if (!response.ok) {
    throw new Error(await getResponseError(response))
  }
  return response.json()
}

export function listUsers() {
  return request('/auth/users')
}

export function createUser(payload) {
  return request('/auth/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateUser(userId, payload) {
  return request(`/auth/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteUser(userId) {
  return request(`/auth/users/${userId}`, {
    method: 'DELETE',
  })
}

export function listWorkspaces() {
  return request('/auth/workspaces')
}

export function createWorkspace(payload) {
  return request('/auth/workspaces', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateWorkspace(workspaceId, payload) {
  return request(`/auth/workspaces/${workspaceId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteWorkspace(workspaceId) {
  return request(`/auth/workspaces/${workspaceId}`, {
    method: 'DELETE',
  })
}
