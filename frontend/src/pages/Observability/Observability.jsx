import { useState, useEffect } from 'react';
import { listSessions, getSessionTraces } from '../../services/api';

const EVENT_ICONS = {
  agent_iteration: '🧠',
  tool_call: '🔧',
  tool_blocked: '🚫',
  tool_result: '📥',
  llm_error: '⚠️',
  limit_exceeded: '🛑',
  subagent_spawn: '🤖',
  error: '❌',
};

const EVENT_COLORS = {
  agent_iteration: 'var(--accent-primary)',
  tool_call: 'var(--info, #3b82f6)',
  tool_blocked: 'var(--error, #ef4444)',
  tool_result: 'var(--success, #22c55e)',
  llm_error: 'var(--warning, #f59e0b)',
  limit_exceeded: 'var(--error, #ef4444)',
  subagent_spawn: '#8b5cf6',
  error: 'var(--error, #ef4444)',
};

export default function Observability() {
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState('');
  const [traces, setTraces] = useState([]);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState({ totalLatency: 0, totalTokens: 0, errors: 0, toolCalls: 0 });
  const [showPhoenix, setShowPhoenix] = useState(false);

  useEffect(() => {
    listSessions()
      .then(data => {
        const s = data.sessions || [];
        setSessions(s);
        if (s.length > 0) setSelectedSession(s[0].id);
      })
      .catch(() => setSessions([]));
  }, []);

  // Fetch traces when session changes
  useEffect(() => {
    if (!selectedSession) return;
    let cancelled = false;
    const fetchTraces = async () => {
      setLoading(true);
      try {
        const data = await getSessionTraces(selectedSession);
        if (cancelled) return;
        const t = data.traces || [];
        setTraces(t);
        setStats({
          totalLatency: t.reduce((s, tr) => s + (tr.latency_ms || 0), 0),
          totalTokens: t.reduce((s, tr) => s + (tr.tokens_used || 0), 0),
          errors: t.filter(tr => tr.is_error).length,
          toolCalls: t.filter(tr => tr.event_type === 'tool_call').length,
        });
      } catch {
        if (!cancelled) setTraces([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchTraces();
    return () => { cancelled = true; };
  }, [selectedSession]);

  return (
    <div className="page-container">
      <h1 className="page-title">Observability</h1>
      <p className="page-subtitle">Agent traces, tool calls, latency, and error tracking</p>

      {/* Session Selector */}
      <div style={{ marginBottom: 20 }}>
        <select
          className="input"
          value={selectedSession}
          onChange={e => setSelectedSession(e.target.value)}
          style={{ maxWidth: 500 }}
        >
          {sessions.map(s => (
            <option key={s.id} value={s.id}>
              {s.title || 'Untitled'} — {new Date(s.created_at).toLocaleDateString()}
            </option>
          ))}
        </select>
        <button 
          className="btn btn-primary" 
          onClick={() => setShowPhoenix(!showPhoenix)}
          style={{ marginLeft: 16 }}
        >
          {showPhoenix ? 'Hide Phoenix UI' : 'Open Phoenix Traces'}
        </button>
      </div>

      {showPhoenix && (
        <div className="card" style={{ padding: 0, height: '70vh', marginBottom: 24, overflow: 'hidden' }}>
          <iframe 
            src="http://localhost:6006" 
            title="Arize Phoenix"
            style={{ width: '100%', height: '100%', border: 'none' }}
          />
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-4" style={{ marginBottom: 24 }}>
        <div className="card animate-fade-in" style={{ animationDelay: '0.05s' }}>
          <div className="stat-card">
            <div className="stat-icon" style={{ background: 'var(--info-bg)', color: 'var(--info)' }}>🔧</div>
            <div>
              <div className="stat-value">{stats.toolCalls}</div>
              <div className="stat-label">Tool Calls</div>
            </div>
          </div>
        </div>
        <div className="card animate-fade-in" style={{ animationDelay: '0.1s' }}>
          <div className="stat-card">
            <div className="stat-icon" style={{ background: 'var(--warning-bg)', color: 'var(--warning)' }}>⚡</div>
            <div>
              <div className="stat-value">{(stats.totalLatency / 1000).toFixed(1)}s</div>
              <div className="stat-label">Total Latency</div>
            </div>
          </div>
        </div>
        <div className="card animate-fade-in" style={{ animationDelay: '0.15s' }}>
          <div className="stat-card">
            <div className="stat-icon" style={{ background: 'var(--accent-glow)', color: 'var(--accent-primary)' }}>📊</div>
            <div>
              <div className="stat-value">{stats.totalTokens.toLocaleString()}</div>
              <div className="stat-label">Tokens</div>
            </div>
          </div>
        </div>
        <div className="card animate-fade-in" style={{ animationDelay: '0.2s' }}>
          <div className="stat-card">
            <div className="stat-icon" style={{ background: 'var(--error-bg)', color: 'var(--error)' }}>🚨</div>
            <div>
              <div className="stat-value">{stats.errors}</div>
              <div className="stat-label">Errors</div>
            </div>
          </div>
        </div>
      </div>

      {/* Trace Timeline */}
      {loading ? (
        <div className="empty-state"><div className="spinner" style={{ margin: '40px auto' }}></div></div>
      ) : traces.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📡</div>
          <div className="empty-state-title">No traces yet</div>
          <p>Run a research session to see agent traces here.</p>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>Agent Trace Timeline</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{traces.length} events</span>
          </div>
          <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
            {traces.map((t, i) => (
              <div
                key={t.id}
                className="animate-fade-in"
                style={{
                  display: 'flex', gap: 14, padding: '12px 20px',
                  borderBottom: '1px solid var(--border)',
                  animationDelay: `${i * 0.02}s`,
                  background: t.is_error ? 'var(--error-bg)' : 'transparent',
                }}
              >
                {/* Icon */}
                <div style={{
                  width: 32, height: 32, borderRadius: 'var(--radius-md)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: t.is_error ? 'var(--error-bg)' : 'var(--bg-tertiary)',
                  fontSize: '0.9rem', flexShrink: 0,
                }}>
                  {EVENT_ICONS[t.event_type] || '•'}
                </div>
                {/* Content */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                    <span style={{
                      fontWeight: 600, fontSize: '0.82rem',
                      color: EVENT_COLORS[t.event_type] || 'var(--text-primary)',
                    }}>
                      {t.event_type.replace(/_/g, ' ').toUpperCase()}
                    </span>
                    {t.tool_name && (
                      <span style={{
                        fontSize: '0.72rem', padding: '2px 8px',
                        background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-full)',
                        fontFamily: 'var(--font-mono)', color: 'var(--text-accent)',
                      }}>
                        {t.tool_name}
                      </span>
                    )}
                  </div>
                  {t.is_error && t.error_detail && (
                    <div style={{ fontSize: '0.78rem', color: 'var(--error)', marginTop: 2 }}>
                      {t.error_detail.slice(0, 200)}
                    </div>
                  )}
                  {/* Show tool input if present */}
                  {!t.is_error && t.input_data && Object.keys(t.input_data).length > 0 && (
                    <div style={{
                      fontSize: '0.72rem', color: 'var(--text-muted)',
                      fontFamily: 'var(--font-mono)', marginTop: 4,
                      background: 'var(--bg-tertiary)', padding: '3px 8px',
                      borderRadius: 4, maxHeight: 60, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {t.input_data.query || t.input_data.message || JSON.stringify(t.input_data).slice(0, 120)}
                    </div>
                  )}
                </div>
                {/* Metrics */}
                <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexShrink: 0 }}>
                  {t.latency_ms > 0 && (
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {t.latency_ms.toFixed(0)}ms
                    </span>
                  )}
                  {t.tokens_used > 0 && (
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {t.tokens_used} tok
                    </span>
                  )}
                  <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                    {t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : ''}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
