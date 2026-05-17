const API_BASE = 'http://localhost:8000';

export async function createSession(query) {
  const res = await fetch(`${API_BASE}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`Create session failed: ${res.status}`);
  return res.json();
}

export async function listSessions() {
  const res = await fetch(`${API_BASE}/api/sessions`);
  if (!res.ok) throw new Error(`List sessions failed: ${res.status}`);
  return res.json();
}

export async function getSession(sessionId) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
  if (!res.ok) throw new Error(`Get session failed: ${res.status}`);
  return res.json();
}

export async function deleteSession(sessionId) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Delete session failed: ${res.status}`);
  return res.json();
}

export async function getSessionTodos(sessionId) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/todos`);
  if (!res.ok) throw new Error(`Get todos failed: ${res.status}`);
  return res.json();
}

export async function getSessionFiles(sessionId, path = '.') {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/files?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`Get files failed: ${res.status}`);
  return res.json();
}

export async function getFileContent(sessionId, path) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/files/content?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`Get file content failed: ${res.status}`);
  return res.json();
}

export async function getSessionMetrics(sessionId) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/metrics`);
  if (!res.ok) throw new Error(`Get metrics failed: ${res.status}`);
  return res.json();
}

export async function getSessionTraces(sessionId, limit = 100) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Get traces failed: ${res.status}`);
  return res.json();
}

export async function getKnowledgeNodes(limit = 50) {
  const res = await fetch(`${API_BASE}/api/knowledge/nodes?limit=${limit}`);
  if (!res.ok) throw new Error(`Get KG nodes failed: ${res.status}`);
  return res.json();
}

export async function getKnowledgeEdges(limit = 100) {
  const res = await fetch(`${API_BASE}/api/knowledge/edges?limit=${limit}`);
  if (!res.ok) throw new Error(`Get KG edges failed: ${res.status}`);
  return res.json();
}

export async function searchKnowledge(query) {
  const res = await fetch(`${API_BASE}/api/knowledge/search?q=${encodeURIComponent(query)}`);
  if (!res.ok) throw new Error(`KG search failed: ${res.status}`);
  return res.json();
}

export async function getExperimentStats() {
  const res = await fetch(`${API_BASE}/api/experiments/stats`);
  if (!res.ok) throw new Error(`Get experiment stats failed: ${res.status}`);
  return res.json();
}

export async function getSessionExperiments(sessionId) {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/experiments`);
  if (!res.ok) throw new Error(`Get experiments failed: ${res.status}`);
  return res.json();
}

export async function getResearchModes() {
  const res = await fetch(`${API_BASE}/api/research/modes`);
  if (!res.ok) throw new Error(`Get modes failed: ${res.status}`);
  return res.json();
}

export async function alignQuery(query, mode = 'deep') {
  const res = await fetch(`${API_BASE}/api/research/align`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, mode }),
  });
  if (!res.ok) throw new Error(`Alignment failed: ${res.status}`);
  return res.json();
}

export async function submitFeedback(sessionId, rating, comment = '', mode = 'deep') {
  const res = await fetch(`${API_BASE}/api/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, rating, comment, mode }),
  });
  if (!res.ok) throw new Error(`Feedback failed: ${res.status}`);
  return res.json();
}

export async function getPreferences() {
  const res = await fetch(`${API_BASE}/api/preferences`);
  if (!res.ok) throw new Error(`Get preferences failed: ${res.status}`);
  return res.json();
}
