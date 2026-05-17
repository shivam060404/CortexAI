export default function Settings() {
  return (
    <div className="page-container">
      <h1 className="page-title">Settings</h1>
      <p className="page-subtitle">Platform configuration and agent execution limits</p>

      <div className="grid grid-2">
        {/* Execution Limits */}
        <div className="card animate-fade-in" style={{ animationDelay: '0.05s' }}>
          <h3 className="card-title" style={{ marginBottom: 16 }}>🛡️ Execution Limits</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {[
              { label: 'Max Iterations', value: '20', desc: 'Maximum agent loop iterations per session' },
              { label: 'Max Tokens', value: '50,000', desc: 'Token budget per research session' },
              { label: 'Timeout', value: '120s', desc: 'Wall-clock time limit per session' },
            ].map((item, i) => (
              <div key={i} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '12px 14px', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border)',
              }}>
                <div>
                  <div style={{ fontSize: '0.88rem', fontWeight: 500 }}>{item.label}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{item.desc}</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.9rem', fontWeight: 600, color: 'var(--accent-primary-hover)' }}>
                  {item.value}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Sub-agent Limits */}
        <div className="card animate-fade-in" style={{ animationDelay: '0.1s' }}>
          <h3 className="card-title" style={{ marginBottom: 16 }}>🤖 Sub-Agent Limits</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {[
              { label: 'Max Tokens', value: '10,000', desc: 'Token budget per sub-agent' },
              { label: 'Max Steps', value: '10', desc: 'Max iterations per sub-agent' },
              { label: 'Timeout', value: '60s', desc: 'Time limit per sub-agent' },
            ].map((item, i) => (
              <div key={i} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '12px 14px', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border)',
              }}>
                <div>
                  <div style={{ fontSize: '0.88rem', fontWeight: 500 }}>{item.label}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{item.desc}</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.9rem', fontWeight: 600, color: 'var(--accent-primary-hover)' }}>
                  {item.value}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Tool Permissions */}
        <div className="card animate-fade-in" style={{ animationDelay: '0.15s' }}>
          <h3 className="card-title" style={{ marginBottom: 16 }}>🔐 Allowed Tools</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {[
              'web_search', 'academic_search', 'news_search',
              'read_file', 'write_file', 'edit_file', 'list_files', 'grep_files',
              'write_todos', 'get_todos', 'spawn_subagent',
            ].map(tool => (
              <span key={tool} className="badge" style={{
                background: 'var(--accent-glow)', color: 'var(--accent-primary-hover)',
                padding: '5px 12px', fontSize: '0.75rem',
              }}>
                {tool}
              </span>
            ))}
          </div>
        </div>

        {/* Resilience */}
        <div className="card animate-fade-in" style={{ animationDelay: '0.2s' }}>
          <h3 className="card-title" style={{ marginBottom: 16 }}>🔄 Resilience Config</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {[
              { label: 'Max Retries', value: '3', desc: 'Retry attempts for failed operations' },
              { label: 'Backoff Factor', value: '2x', desc: 'Exponential backoff multiplier' },
              { label: 'Circuit Breaker', value: '5 fails', desc: 'Threshold to trip circuit breaker' },
              { label: 'Search Cache TTL', value: '1 hour', desc: 'Cached Tavily results expiry' },
            ].map((item, i) => (
              <div key={i} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '12px 14px', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border)',
              }}>
                <div>
                  <div style={{ fontSize: '0.88rem', fontWeight: 500 }}>{item.label}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{item.desc}</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.9rem', fontWeight: 600, color: 'var(--accent-primary-hover)' }}>
                  {item.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
