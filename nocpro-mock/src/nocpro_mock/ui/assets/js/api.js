/**
 * API client module for NocPro Mock Studio.
 * Handles base URLs, query string serialization, and error normalization.
 */

const BASE_PREFIX = (typeof window !== 'undefined' && window.location.pathname.startsWith('/mock-studio')) ? '/mock-studio' : '';

async function request(endpoint, options = {}) {
  const url = `${BASE_PREFIX}${endpoint}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  if (config.body && typeof config.body === 'object') {
    config.body = JSON.stringify(config.body);
  }

  const response = await fetch(url, config);
  const data = await response.json().catch(() => ({ ok: false, error: 'Non-JSON response' }));

  if (!response.ok) {
    const error = new Error(data.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

export const api = {
  getStatus() {
    return request('/api/status');
  },

  checkKafka(bootstrap) {
    return request('/api/check-kafka', {
      method: 'POST',
      body: bootstrap ? { kafka_bootstrap: bootstrap } : {},
    });
  },

  getDatasets() {
    return request('/api/datasets');
  },

  getAlarms(params = {}) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') {
        qs.append(k, v);
      }
    });
    return request(`/api/alarms?${qs.toString()}`);
  },

  getAlarmFacets(datasetId = 'alarm_data') {
    return request(`/api/alarm-facets?dataset_id=${encodeURIComponent(datasetId)}`);
  },

  getAlarmDetail(datasetId, rowId) {
    return request(`/api/alarms/${encodeURIComponent(datasetId)}/${encodeURIComponent(rowId)}`);
  },

  getTopologyProfiles() {
    return request('/api/topology/profiles');
  },

  getTopologyMetadata(profileId = 'IP_NETWORK') {
    return request(`/api/topology/metadata?profile_id=${encodeURIComponent(profileId)}`);
  },

  getTopologyRoots(profileId = 'IT_SERVICES', limit = 10000) {
    const qs = new URLSearchParams({ profile_id: profileId, limit: String(limit) });
    return request(`/api/topology/roots?${qs.toString()}`);
  },

  getTopologyProjection(profileId, rootId = '', depth = 2, childLimit = 10000) {
    const qs = new URLSearchParams({ profile_id: profileId, depth: String(depth), child_limit: String(childLimit) });
    if (rootId) qs.append('root_id', rootId);
    return request(`/api/topology/projection?${qs.toString()}`);
  },

  searchTopology(profileId, query, limit = 20) {
    const qs = new URLSearchParams({ profile_id: profileId, q: query, limit: String(limit) });
    return request(`/api/topology/search?${qs.toString()}`);
  },

  resolveTopologyIdentifier(profileId, identifier) {
    const qs = new URLSearchParams({ profile_id: profileId, identifier });
    return request(`/api/topology/resolve?${qs.toString()}`);
  },

  submitTopologyPublish(payload) {
    return request('/api/topology-publish-jobs', {
      method: 'POST',
      body: payload,
    });
  },

  submitSliceJob(payload) {
    return request('/api/slice-jobs', {
      method: 'POST',
      body: payload,
    });
  },

  submitPublishJob(payload) {
    return request('/api/publish-jobs', {
      method: 'POST',
      body: payload,
    });
  },

  getJobs(limit = 50) {
    return request(`/api/jobs?limit=${limit}`);
  },

  getJob(jobId) {
    return request(`/api/jobs/${encodeURIComponent(jobId)}`);
  },

  pauseJob(jobId) {
    return request(`/api/jobs/${encodeURIComponent(jobId)}/pause`, { method: 'POST' });
  },

  resumeJob(jobId) {
    return request(`/api/jobs/${encodeURIComponent(jobId)}/resume`, { method: 'POST' });
  },

  stopJob(jobId) {
    return request(`/api/jobs/${encodeURIComponent(jobId)}/stop`, { method: 'POST' });
  },

  getSseUrl(jobId) {
    return `${BASE_PREFIX}/api/jobs/${encodeURIComponent(jobId)}/events`;
  },
};
