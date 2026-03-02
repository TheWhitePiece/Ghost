/**
 * API service for communicating with the Supply Chain Ghost backend.
 */
const API_BASE = process.env.REACT_APP_API_URL || '/v1';

async function getAuthToken() {
  try {
    const { fetchAuthSession } = await import('aws-amplify/auth');
    const session = await fetchAuthSession();
    return session.tokens?.idToken?.toString() || '';
  } catch {
    return '';
  }
}

async function apiRequest(path, options = {}) {
  const token = await getAuthToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : '',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Request failed' }));
    throw new Error(error.error || `HTTP ${response.status}`);
  }

  return response.json();
}

export const api = {
  // Dashboard KPIs
  getDashboard: () => apiRequest('/dashboard'),

  // Signals
  getSignals: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return apiRequest(`/signals?${query}`);
  },

  // Risk Assessments
  getRisks: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return apiRequest(`/risks?${query}`);
  },
  getRiskDetail: (id) => apiRequest(`/risks/${id}`),
  approveRisk: (id, data) => apiRequest(`/risks/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  // Chat
  chat: (message, assessmentId = '', history = []) => apiRequest('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, assessment_id: assessmentId, history }),
  }),

  // Simulate
  simulate: (data) => apiRequest('/simulate', {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  // Audit
  getAuditTrail: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return apiRequest(`/audit?${query}`);
  },
};
