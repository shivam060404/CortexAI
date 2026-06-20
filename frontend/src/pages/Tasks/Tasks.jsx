import { useState, useEffect } from 'react';
import { listSessions, getSessionTodos } from '../../services/api';

const STATUS_CONFIG = {
  pending: { icon: '⏳', color: 'var(--info)', bg: 'var(--info-bg)' },
  in_progress: { icon: '🔄', color: 'var(--warning)', bg: 'var(--warning-bg)' },
  completed: { icon: '✅', color: 'var(--success)', bg: 'var(--success-bg)' },
  failed: { icon: '❌', color: 'var(--error)', bg: 'var(--error-bg)' },
};

export default function Tasks() {
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [todos, setTodos] = useState([]);
  const [, setLoading] = useState(true);

  useEffect(() => {
    listSessions().then(data => {
      const s = data.sessions || [];
      setSessions(s);
      if (s.length > 0) setSelectedSession(s[0].id);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (selectedSession) {
      getSessionTodos(selectedSession).then(data => setTodos(data.todos || [])).catch(() => setTodos([]));
    }
  }, [selectedSession]);

  const stats = {
    total: todos.length,
    pending: todos.filter(t => t.status === 'pending').length,
    inProgress: todos.filter(t => t.status === 'in_progress').length,
    completed: todos.filter(t => t.status === 'completed').length,
    failed: todos.filter(t => t.status === 'failed').length,
  };

  const completionRate = stats.total > 0 ? Math.round((stats.completed / stats.total) * 100) : 0;

  return (
    <div className="page-container">
      <h1 className="page-title">Tasks</h1>
      <p className="page-subtitle">Agent's dynamic research plan — task state machine view</p>

      {/* Session Selector */}
      {sessions.length > 0 && (
        <div style={{ marginBottom: 20, maxWidth: 400 }}>
          <select
            className="input"
            value={selectedSession || ''}
            onChange={(e) => setSelectedSession(e.target.value)}
            id="tasks-session-select"
          >
            {sessions.map(s => (
              <option key={s.id} value={s.id}>{s.title}</option>
            ))}
          </select>
        </div>
      )}

      {todos.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📋</div>
          <div className="empty-state-title">No tasks yet</div>
          <p>The agent will create tasks when it starts researching.</p>
        </div>
      ) : (
        <>
          {/* Progress bar */}
          <div className="card" style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                Progress: {stats.completed}/{stats.total} tasks
              </span>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                {completionRate}%
              </span>
            </div>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${completionRate}%` }}></div>
            </div>
            <div className="metrics-bar" style={{ marginTop: 14 }}>
              {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
                <div key={key} className="metric-item">
                  <span>{cfg.icon}</span>
                  <span style={{ textTransform: 'capitalize' }}>{key.replace('_', ' ')}:</span>
                  <span className="metric-value">{stats[key === 'in_progress' ? 'inProgress' : key]}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Task List */}
          <div className="card">
            <h3 className="card-title" style={{ marginBottom: 16 }}>Research Plan</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {todos.map((todo, i) => {
                const cfg = STATUS_CONFIG[todo.status] || STATUS_CONFIG.pending;
                return (
                  <div key={i} className="animate-fade-in" style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 16px', borderRadius: 'var(--radius-md)',
                    background: 'var(--bg-tertiary)', border: '1px solid var(--border)',
                    animationDelay: `${i * 0.05}s`,
                  }}>
                    <span style={{ fontSize: '1.1rem' }}>{cfg.icon}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '0.88rem', color: 'var(--text-primary)' }}>{todo.text}</div>
                      {todo.error_message && (
                        <div style={{ fontSize: '0.75rem', color: 'var(--error)', marginTop: 4 }}>
                          Error: {todo.error_message}
                        </div>
                      )}
                    </div>
                    <span className={`badge badge-${todo.status.replace('_', '-')}`}>
                      {todo.status.replace('_', ' ')}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
