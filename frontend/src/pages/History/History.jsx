import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listSessions, deleteSession } from '../../services/api';

export default function History() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const loadSessions = () => {
    setLoading(true);
    listSessions()
      .then(data => setSessions(data.sessions || []))
      .catch(() => setSessions([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadSessions(); }, []);

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    if (confirm('Delete this research session?')) {
      await deleteSession(id);
      loadSessions();
    }
  };

  return (
    <div className="page-container">
      <h1 className="page-title">History</h1>
      <p className="page-subtitle">All past research sessions</p>

      {loading ? (
        <div className="empty-state"><div className="spinner" style={{ margin: '40px auto' }}></div></div>
      ) : sessions.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🕐</div>
          <div className="empty-state-title">No research history</div>
          <p>Your completed research sessions will appear here.</p>
        </div>
      ) : (
        <div className="card">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {sessions.map((s, i) => (
              <div
                key={s.id}
                onClick={() => navigate(`/research?session=${s.id}`)}
                className="animate-fade-in"
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '14px 16px', borderRadius: 'var(--radius-md)',
                  cursor: 'pointer', transition: 'background 0.15s',
                  animationDelay: `${i * 0.04}s`,
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-tertiary)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: '0.92rem', marginBottom: 4 }}>{s.title}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', gap: 16 }}>
                    <span>📅 {new Date(s.created_at).toLocaleString()}</span>
                    <span>📊 {s.tokens_used?.toLocaleString() || 0} tokens</span>
                    <span>🔧 {s.tool_calls_count || 0} tool calls</span>
                    <span>🔄 {s.iterations_used || 0} iterations</span>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className={`badge badge-${s.status}`}>{s.status}</span>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={(e) => handleDelete(e, s.id)}
                    style={{ color: 'var(--text-muted)' }}
                  >🗑</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
