const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const ACCESS_TOKEN_KEY = 'cortexai_access_token';
const REFRESH_TOKEN_KEY = 'cortexai_refresh_token';

export function getApiBase() {
  return API_BASE;
}

export function getToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshTokenValue() {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setAuthTokens({ access_token, refresh_token }) {
  if (access_token) localStorage.setItem(ACCESS_TOKEN_KEY, access_token);
  if (refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, refresh_token);
}

export function clearAuthTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function isAuthenticated() {
  return Boolean(getToken());
}

function redirectToLogin() {
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

async function parseResponse(res) {
  const contentType = res.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = typeof payload === 'string' ? payload : payload?.detail || `Request failed: ${res.status}`;
    throw new Error(detail);
  }
  return payload;
}

async function apiFetch(path, options = {}, retryOn401 = true) {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', headers.get('Content-Type') || 'application/json');

  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 401 && retryOn401 && getRefreshTokenValue()) {
    try {
      await refreshToken();
      return apiFetch(path, options, false);
    } catch (error) {
      clearAuthTokens();
      redirectToLogin();
      throw error;
    }
  }

  return parseResponse(response);
}

export async function register(email, password, fullName = '') {
  const payload = await apiFetch('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, full_name: fullName || null }),
  }, false);
  setAuthTokens(payload);
  return payload;
}

export async function login(email, password) {
  const payload = await apiFetch('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  }, false);
  setAuthTokens(payload);
  return payload;
}

export async function refreshToken() {
  const refresh = getRefreshTokenValue();
  if (!refresh) {
    throw new Error('No refresh token available');
  }

  const response = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${refresh}`,
    },
  });

  const payload = await parseResponse(response);
  setAuthTokens(payload);
  return payload;
}

export async function getCurrentUser() {
  return apiFetch('/api/auth/me');
}

export async function generateApiKey() {
  return apiFetch('/api/auth/api-key', { method: 'POST' });
}

export async function getOAuthUrl(provider, redirectUri) {
  const res = await apiFetch(`/api/auth/${provider}?redirect_uri=${encodeURIComponent(redirectUri)}`, {}, false);
  return res.auth_url;
}

export async function exchangeOAuthCode(provider, code, redirectUri) {
  const payload = await apiFetch(`/api/auth/${provider}/callback`, {
    method: 'POST',
    body: JSON.stringify({ code, redirect_uri: redirectUri }),
  }, false);
  setAuthTokens(payload);
  return payload;
}

export async function loginWithGoogle(redirectUri) {
  const authUrl = await getOAuthUrl('google', redirectUri);
  window.location.href = authUrl;
}

export async function loginWithGithub(redirectUri) {
  const authUrl = await getOAuthUrl('github', redirectUri);
  window.location.href = authUrl;
}

export async function createSession(query) {
  return apiFetch('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ query }),
  });
}

export async function listSessions() {
  return apiFetch('/api/sessions');
}

export async function getSession(sessionId) {
  return apiFetch(`/api/sessions/${sessionId}`);
}

export async function deleteSession(sessionId) {
  return apiFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
}

export async function getSessionTodos(sessionId) {
  return apiFetch(`/api/sessions/${sessionId}/todos`);
}

export async function getSessionFiles(sessionId, path = '.') {
  return apiFetch(`/api/sessions/${sessionId}/files?path=${encodeURIComponent(path)}`);
}

export async function getFileContent(sessionId, path) {
  return apiFetch(`/api/sessions/${sessionId}/files/content?path=${encodeURIComponent(path)}`);
}

export async function getSessionMetrics(sessionId) {
  return apiFetch(`/api/sessions/${sessionId}/metrics`);
}

export async function getSessionTraces(sessionId, limit = 100) {
  return apiFetch(`/api/sessions/${sessionId}/traces?limit=${limit}`);
}

export async function getKnowledgeNodes(limit = 50) {
  return apiFetch(`/api/knowledge/nodes?limit=${limit}`);
}

export async function getKnowledgeEdges(limit = 100) {
  return apiFetch(`/api/knowledge/edges?limit=${limit}`);
}

export async function searchKnowledge(query) {
  return apiFetch(`/api/knowledge/search?q=${encodeURIComponent(query)}`);
}

export async function getExperimentStats() {
  return apiFetch('/api/experiments/stats');
}

export async function getSessionExperiments(sessionId) {
  return apiFetch(`/api/sessions/${sessionId}/experiments`);
}

export async function getResearchModes() {
  return apiFetch('/api/research/modes');
}

export async function alignQuery(query, mode = 'deep') {
  return apiFetch('/api/research/align', {
    method: 'POST',
    body: JSON.stringify({ query, mode }),
  });
}

export async function submitFeedback(sessionId, rating, comment = '', mode = 'deep') {
  return apiFetch('/api/feedback', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, rating, comment, mode }),
  });
}

export async function getPreferences() {
  return apiFetch('/api/preferences');
}

// --- Document Upload ---

export async function uploadDocument(file, sessionId = 'default') {
  const token = getToken();
  const formData = new FormData();
  formData.append('file', file);
  formData.append('session_id', sessionId);

  const response = await fetch(`${API_BASE}/api/upload`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  return parseResponse(response);
}

export async function uploadDocumentsBatch(files, sessionId = 'default') {
  const token = getToken();
  const formData = new FormData();
  files.forEach(f => formData.append('files', f));
  formData.append('session_id', sessionId);

  const response = await fetch(`${API_BASE}/api/upload/batch`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  return parseResponse(response);
}
