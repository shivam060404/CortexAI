import { useState, useEffect } from 'react';
import { getKnowledgeNodes, getKnowledgeEdges, searchKnowledge } from '../../services/api';

const TYPE_COLORS = {
  concept: { bg: 'var(--accent-glow)', color: 'var(--accent-primary)', icon: '💡' },
  paper: { bg: 'var(--info-bg)', color: 'var(--info)', icon: '📄' },
  entity: { bg: 'var(--success-bg)', color: 'var(--success)', icon: '🏷️' },
  finding: { bg: 'var(--warning-bg)', color: 'var(--warning)', icon: '🔍' },
};

export default function KnowledgeGraph() {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState(null);
  const [tab, setTab] = useState('nodes'); // nodes | edges | search

  useEffect(() => {
    Promise.all([getKnowledgeNodes(), getKnowledgeEdges()])
      .then(([nodeData, edgeData]) => {
        setNodes(nodeData.nodes || []);
        setEdges(edgeData.edges || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setTab('search');
    const data = await searchKnowledge(searchQuery).catch(() => ({ results: [] }));
    setSearchResults(data.results || []);
  };

  const nodesByType = {};
  nodes.forEach(n => {
    const t = n.node_type || 'concept';
    if (!nodesByType[t]) nodesByType[t] = [];
    nodesByType[t].push(n);
  });

  const getStyle = (type) => TYPE_COLORS[type] || TYPE_COLORS.concept;

  return (
    <div className="page-container">
      <h1 className="page-title">Knowledge Graph</h1>
      <p className="page-subtitle">Explore the persistent "second brain" — concepts, papers, and relationships</p>

      {/* Stats */}
      <div className="grid grid-3" style={{ marginBottom: 24 }}>
        <div className="card animate-fade-in" style={{ animationDelay: '0.05s' }}>
          <div className="stat-card">
            <div className="stat-icon" style={{ background: 'var(--accent-glow)', color: 'var(--accent-primary)' }}>🧠</div>
            <div>
              <div className="stat-value">{nodes.length}</div>
              <div className="stat-label">Concepts</div>
            </div>
          </div>
        </div>
        <div className="card animate-fade-in" style={{ animationDelay: '0.1s' }}>
          <div className="stat-card">
            <div className="stat-icon" style={{ background: 'var(--info-bg)', color: 'var(--info)' }}>🔗</div>
            <div>
              <div className="stat-value">{edges.length}</div>
              <div className="stat-label">Relationships</div>
            </div>
          </div>
        </div>
        <div className="card animate-fade-in" style={{ animationDelay: '0.15s' }}>
          <div className="stat-card">
            <div className="stat-icon" style={{ background: 'var(--success-bg)', color: 'var(--success)' }}>📂</div>
            <div>
              <div className="stat-value">{Object.keys(nodesByType).length}</div>
              <div className="stat-label">Node Types</div>
            </div>
          </div>
        </div>
      </div>

      {/* Search Bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <input
          className="input"
          placeholder="Search concepts, papers, or findings..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          style={{ flex: 1, maxWidth: 500 }}
        />
        <button className="btn btn-primary" onClick={handleSearch}>Search</button>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20 }}>
        {['nodes', 'edges', 'search'].map(t => (
          <button
            key={t}
            className={`btn ${tab === t ? 'btn-primary' : 'btn-ghost'} btn-sm`}
            onClick={() => setTab(t)}
          >
            {t === 'nodes' ? '🧠 Concepts' : t === 'edges' ? '🔗 Relations' : '🔍 Search'}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="empty-state"><div className="spinner" style={{ margin: '40px auto' }}></div></div>
      ) : tab === 'nodes' ? (
        /* Nodes View */
        nodes.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🧠</div>
            <div className="empty-state-title">Knowledge graph is empty</div>
            <p>Run research sessions — the agent will populate the graph automatically.</p>
          </div>
        ) : (
          <div>
            {Object.entries(nodesByType).map(([type, typeNodes]) => {
              const style = getStyle(type);
              return (
                <div key={type} style={{ marginBottom: 24 }}>
                  <h3 style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {style.icon} {type} ({typeNodes.length})
                  </h3>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {typeNodes.map((n, i) => (
                      <div
                        key={n.id}
                        className="animate-fade-in"
                        style={{
                          padding: '8px 16px', borderRadius: 'var(--radius-full)',
                          background: style.bg, color: style.color,
                          fontSize: '0.82rem', fontWeight: 500,
                          cursor: 'pointer', border: `1px solid ${style.color}20`,
                          transition: 'all var(--transition-fast)',
                          animationDelay: `${i * 0.02}s`,
                        }}
                        onClick={() => setSelectedNode(selectedNode?.id === n.id ? null : n)}
                        onMouseEnter={e => { e.currentTarget.style.transform = 'scale(1.05)'; e.currentTarget.style.boxShadow = `0 0 12px ${style.color}40`; }}
                        onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.boxShadow = 'none'; }}
                      >
                        {n.name}
                        {n.edge_count > 0 && (
                          <span style={{ marginLeft: 6, opacity: 0.7, fontSize: '0.7rem' }}>({n.edge_count})</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}

            {/* Node detail sidebar */}
            {selectedNode && (
              <div className="card animate-slide-in" style={{ marginTop: 16, borderColor: 'var(--border-accent)' }}>
                <div className="card-header">
                  <span className="card-title">{selectedNode.name}</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => setSelectedNode(null)}>✕</button>
                </div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                  <p><strong>Type:</strong> {selectedNode.node_type}</p>
                  <p><strong>Connections:</strong> {selectedNode.edge_count}</p>
                  <p><strong>Added:</strong> {selectedNode.created_at ? new Date(selectedNode.created_at).toLocaleString() : 'Unknown'}</p>
                  {/* Show edges involving this node */}
                  {edges.filter(e => e.source_id === selectedNode.id || e.target_id === selectedNode.id).length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <strong>Relations:</strong>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
                        {edges.filter(e => e.source_id === selectedNode.id || e.target_id === selectedNode.id).map(e => (
                          <div key={e.id} style={{ padding: '6px 10px', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', fontSize: '0.78rem' }}>
                            {e.source_id === selectedNode.id
                              ? `→ [${e.relation}] ${e.target}`
                              : `← [${e.relation}] ${e.source}`
                            }
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      ) : tab === 'edges' ? (
        /* Edges View */
        edges.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🔗</div>
            <div className="empty-state-title">No relationships yet</div>
          </div>
        ) : (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
              {edges.map((e, i) => (
                <div
                  key={e.id}
                  className="animate-fade-in"
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 20px', borderBottom: '1px solid var(--border)',
                    animationDelay: `${i * 0.02}s`,
                  }}
                >
                  <span style={{ fontWeight: 500, fontSize: '0.85rem', color: 'var(--text-accent)' }}>{e.source}</span>
                  <span style={{
                    padding: '2px 10px', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-full)',
                    fontSize: '0.72rem', color: 'var(--text-muted)', fontStyle: 'italic',
                  }}>
                    {e.relation}
                  </span>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>→</span>
                  <span style={{ fontWeight: 500, fontSize: '0.85rem', color: 'var(--success)' }}>{e.target}</span>
                </div>
              ))}
            </div>
          </div>
        )
      ) : (
        /* Search Results */
        searchResults === null ? (
          <div className="empty-state">
            <div className="empty-state-icon">🔍</div>
            <div className="empty-state-title">Enter a query to search</div>
          </div>
        ) : searchResults.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🤷</div>
            <div className="empty-state-title">No results for "{searchQuery}"</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {searchResults.map((r, i) => (
              <div key={r.id} className="card animate-fade-in" style={{ animationDelay: `${i * 0.05}s` }}>
                <div className="card-header">
                  <span className="card-title">{r.name}</span>
                  <span className="badge badge-pending">{r.node_type}</span>
                </div>
                {r.relations.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {r.relations.map((rel, j) => (
                      <div key={j} style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', paddingLeft: 8, borderLeft: '2px solid var(--border-light)' }}>
                        {rel}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}
