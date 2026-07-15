import { request } from './base'

export function listModelProviders() {
  return request('/model-providers')
}

export function createModelProvider(payload) {
  return request('/model-providers', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateModelProvider(providerId, payload) {
  return request(`/model-providers/${encodeURIComponent(providerId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteModelProvider(providerId) {
  return request(`/model-providers/${encodeURIComponent(providerId)}`, {
    method: 'DELETE',
  })
}

export function fetchRemoteModels(providerId) {
  return request(`/model-providers/${encodeURIComponent(providerId)}/remote-models`)
}

export function refreshModelCache() {
  return request('/model-providers/models/cache/refresh', { method: 'POST' })
}

export function listModels(modelType = 'chat') {
  return request(`/model-providers/models/v2?model_type=${encodeURIComponent(modelType)}`)
}

export function getModelStatus(spec) {
  return request(`/model-providers/models/status?spec=${encodeURIComponent(spec)}`)
}

export function testModelProviderCredentials(payload) {
  return request('/model-providers/test-credentials', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function testProviderModel(providerId, payload) {
  return request(`/model-providers/${encodeURIComponent(providerId)}/models/test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listModelUses() {
  return request('/model-providers/model-uses')
}

export function updateModelUse(modelUse, modelSpec) {
  return request(`/model-providers/model-uses/${encodeURIComponent(modelUse)}`, {
    method: 'PUT',
    body: JSON.stringify({ model_spec: modelSpec }),
  })
}
