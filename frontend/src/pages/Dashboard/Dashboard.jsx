import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listSessions } from '../../services/api';
import './Dashboard.css';

export default function Dashboard() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    listSessions()
      .then(data => setSessions(data.sessions || []))
      .catch(() => setSessions([]))
      .finally(() => setLoading(false));
  }, []);

  const stats = {
    total: sessions.length,
    running: sessions.filter(s => s.status === 'running').length,
    completed: sessions.filter(s => s.status === 'completed').length,
    totalTokens: sessions.reduce((sum, s) => sum + (s.tokens_used || 0), 0),
    totalTools: sessions.reduce((sum, s) => sum + (s.tool_calls_count || 0), 0),
  };

  return (
    <div className="page-container">
      {/* Hero Section */}
      <div className="dash-hero animate-fade-in">
        <div className="dash-hero-content">
          <div className="dash-hero-badge">AI Research Lab</div>
          <h1 className="dash-hero-title">CortexAI</h1>
          <p className="dash-hero-desc">
            Autonomous deep research with self-reflection, failure memory, parallel sub-agents, and a persistent knowledge graph.
          </p>
          <button className="btn btn-primary btn-lg" onClick={() => navigate('/research')} id="quick-start-btn">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            Start New Research
          </button>
        </div>
        <div className="dash-hero-glow" />
      </div>

      {/* Stats Grid */}
      <div className="grid grid-4 dash-stats">
        {[
          { icon: '🔬', value: stats.total, label: 'Total Sessions', color: 'var(--accent-primary)', bg: 'var(--accent-glow)' },
          { icon: '⚡', value: stats.running, label: 'Active Now', color: 'var(--warning)', bg: 'var(--warning-bg)' },
          { icon: '✅', value: stats.completed, label: 'Completed', color: 'var(--success)', bg: 'var(--success-bg)' },
          { icon: '📊', value: stats.totalTokens.toLocaleString(), label: 'Tokens Used', color: 'var(--info)', bg: 'var(--info-bg)' },
        ].map((s, i) => (
          <div key={i} className="card animate-fade-in" style={{ animationDelay: `${0.1 + i * 0.05}s` }}>
            <div className="stat-card">
              <div className="stat-icon" style={{ background: s.bg, color: s.color }}>{s.icon}</div>
              <div>
                <div className="stat-value">{s.value}</div>
                <div className="stat-label">{s.label}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Capabilities Grid */}
      <div className="grid grid-2" style={{ marginTop: 20 }}>
        <div className="card animate-fade-in" style={{ animationDelay: '0.3s' }}>
          <h3 className="card-title" style={{ marginBottom: 16 }}>🧠 Intelligence Layer</h3>
          <div className="capability-grid">
            {[
              { icon: '🪞', name: 'Self-Reflection', desc: 'Scores own work before final output' },
              { icon: '🧠', name: 'Failure Memory', desc: 'Never repeats broken approaches' },
              { icon: '⚡', name: 'Parallel Agents', desc: 'Multiple specialists run simultaneously' },
              { icon: '🔁', name: 'Research Loop', desc: 'Hypothesize → test → evaluate → refine' },
              { icon: '🗃️', name: 'Knowledge Graph', desc: 'Persistent cross-session memory' },
              { icon: '👤', name: 'Personalization', desc: 'Learns your research interests' },
            ].map((c, i) => (
              <div key={i} className="capability-item">
                <span className="capability-icon">{c.icon}</span>
                <div>
                  <div className="capability-name">{c.name}</div>
                  <div className="capability-desc">{c.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card animate-fade-in" style={{ animationDelay: '0.35s' }}>
          <h3 className="card-title" style={{ marginBottom: 16 }}>🛡️ Production Safety</h3>
          <div className="capability-grid">
            {[
              { icon: '⏱', name: 'Execution Guard', desc: '20 iter / 50K token / 120s limits' },
              { icon: '🔒', name: 'Tool Guard', desc: 'Strict allowlist for all tools' },
              { icon: '🔄', name: 'Retry + Breaker', desc: '3x retry with circuit breaker' },
              { icon: '📡', name: 'Full Observability', desc: 'Every step traced to PostgreSQL' },
              { icon: '💾', name: 'DB Persistence', desc: 'Sessions survive server restarts' },
              { icon: '🛑', name: 'Crash Recovery', desc: 'WebSocket cleanup on all exits' },
            ].map((c, i) => (
              <div key={i} className="capability-item">
                <span className="capability-icon">{c.icon}</span>
                <div>
                  <div className="capability-name">{c.name}</div>
                  <div className="capability-desc">{c.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent Sessions */}
      {sessions.length > 0 && (
        <div className="card animate-fade-in" style={{ marginTop: 20, animationDelay: '0.4s' }}>
          <div className="card-header">
            <span className="card-title">Recent Research</span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/history')}>View All →</button>
          </div>
          <div className="sessions-list">
            {sessions.slice(0, 5).map(s => (
              <div key={s.id} className="session-row" onClick={() => navigate(`/research?session=${s.id}`)}>
                <div className="session-info">
                  <div className="session-title">{s.title}</div>
                  <div className="session-meta">
                    {new Date(s.created_at).toLocaleDateString()} · {(s.tokens_used || 0).toLocaleString()} tokens · {s.tool_calls_count || 0} tools
                  </div>
                </div>
                <span className={`badge badge-${s.status}`}>{s.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
