import { useState, useCallback, useRef } from 'react';
import './Workflow.css';

// =============================================================================
// Visual Workflow Builder — Phase 3
// =============================================================================
// Drag-and-drop visual DAG editor for building research workflows.
// Nodes represent research steps (search, analyze, synthesize, export).
// Edges represent data flow between steps.
// =============================================================================

const NODE_TYPES = {
  search:     { label: 'Search',     icon: '🔍', color: '#3B82F6', description: 'Web/academic search' },
  analyze:    { label: 'Analyze',    icon: '🔬', color: '#8B5CF6', description: 'Analyze & extract insights' },
  synthesize: { label: 'Synthesize', icon: '🧠', color: '#10B981', description: 'Combine multiple results' },
  filter:     { label: 'Filter',     icon: '🔧', color: '#F59E0B', description: 'Filter & refine results' },
  export:     { label: 'Export',     icon: '📄', color: '#EF4444', description: 'Export to PDF/DOCX/PPTX' },
  rag:        { label: 'RAG Query',  icon: '📚', color: '#6366F1', description: 'Query knowledge base' },
  human:      { label: 'Human Review', icon: '👤', color: '#EC4899', description: 'Human-in-the-loop checkpoint' },
  condition:  { label: 'Condition',  icon: '❓', color: '#14B8A6', description: 'Conditional branching' },
};

let nodeIdCounter = 0;
function generateNodeId() { return `node_${++nodeIdCounter}_${Date.now()}`; }

export default function Workflow() {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);
  const [dragging, setDragging] = useState(null);
  const [connecting, setConnecting] = useState(null);
  const [workflowName, setWorkflowName] = useState('New Research Workflow');
  const [showPalette, setShowPalette] = useState(true);
  const [executionLog, setExecutionLog] = useState([]);
  const [isExecuting, setIsExecuting] = useState(false);
  const canvasRef = useRef(null);

  // --- Add node ---
  const addNode = useCallback((type, x, y) => {
    const nodeConfig = NODE_TYPES[type];
    const newNode = {
      id: generateNodeId(),
      type,
      label: nodeConfig.label,
      icon: nodeConfig.icon,
      color: nodeConfig.color,
      description: nodeConfig.description,
      x: x || 100 + Math.random() * 300,
      y: y || 100 + Math.random() * 200,
      config: { query: '', maxResults: 5, depth: 'standard' },
    };
    setNodes(prev => [...prev, newNode]);
    setSelectedNode(newNode.id);
  }, []);

  // --- Delete node ---
  const deleteNode = useCallback((nodeId) => {
    setNodes(prev => prev.filter(n => n.id !== nodeId));
    setEdges(prev => prev.filter(e => e.from !== nodeId && e.to !== nodeId));
    if (selectedNode === nodeId) setSelectedNode(null);
  }, [selectedNode]);

  // --- Start connection ---
  const startConnection = useCallback((nodeId, e) => {
    e.stopPropagation();
    setConnecting(nodeId);
  }, []);

  // --- Complete connection ---
  const completeConnection = useCallback((targetNodeId) => {
    if (connecting && connecting !== targetNodeId) {
      const exists = edges.some(e => e.from === connecting && e.to === targetNodeId);
      if (!exists) {
        setEdges(prev => [...prev, {
          id: `edge_${connecting}_${targetNodeId}`,
          from: connecting,
          to: targetNodeId,
        }]);
      }
    }
    setConnecting(null);
  }, [connecting, edges]);

  // --- Drag nodes ---
  const handleMouseDown = useCallback((e, nodeId) => {
    if (connecting) { completeConnection(nodeId); return; }
    const node = nodes.find(n => n.id === nodeId);
    if (!node) return;
    const rect = canvasRef.current?.getBoundingClientRect();
    setDragging({
      nodeId,
      offsetX: e.clientX - (rect?.left || 0) - node.x,
      offsetY: e.clientY - (rect?.top || 0) - node.y,
    });
    setSelectedNode(nodeId);
  }, [nodes, connecting, completeConnection]);

  const handleMouseMove = useCallback((e) => {
    if (!dragging || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = Math.max(0, e.clientX - rect.left - dragging.offsetX);
    const y = Math.max(0, e.clientY - rect.top - dragging.offsetY);
    setNodes(prev => prev.map(n =>
      n.id === dragging.nodeId ? { ...n, x, y } : n
    ));
  }, [dragging]);

  const handleMouseUp = useCallback(() => setDragging(null), []);

  // --- Update node config ---
  const updateNodeConfig = useCallback((nodeId, key, value) => {
    setNodes(prev => prev.map(n =>
      n.id === nodeId ? { ...n, config: { ...n.config, [key]: value } } : n
    ));
  }, []);

  // --- Execute workflow ---
  const executeWorkflow = useCallback(async () => {
    if (nodes.length === 0) return;
    setIsExecuting(true);
    setExecutionLog([]);

    // Topological sort for execution order
    const sorted = topologicalSort(nodes, edges);

    for (const nodeId of sorted) {
      const node = nodes.find(n => n.id === nodeId);
      if (!node) continue;

      setExecutionLog(prev => [...prev, {
        nodeId, label: node.label, status: 'running', time: new Date().toLocaleTimeString(),
      }]);

      // Simulate execution
      await new Promise(resolve => setTimeout(resolve, 800 + Math.random() * 1200));

      setExecutionLog(prev => prev.map(log =>
        log.nodeId === nodeId ? { ...log, status: 'complete' } : log
      ));
    }

    setIsExecuting(false);
  }, [nodes, edges]);

  // --- Export workflow as JSON ---
  const exportWorkflow = useCallback(() => {
    const data = { name: workflowName, nodes, edges, exportedAt: new Date().toISOString() };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${workflowName.replace(/\s+/g, '_')}.json`; a.click();
    URL.revokeObjectURL(url);
  }, [workflowName, nodes, edges]);

  // --- Import workflow ---
  const importWorkflow = useCallback((e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result);
        if (data.nodes && data.edges) {
          setNodes(data.nodes);
          setEdges(data.edges);
          if (data.name) setWorkflowName(data.name);
        }
      } catch { alert('Invalid workflow file'); }
    };
    reader.readAsText(file);
  }, []);

  const selectedNodeData = nodes.find(n => n.id === selectedNode);

  return (
    <div className="workflow-page">
      {/* Toolbar */}
      <div className="workflow-toolbar">
        <input
          className="workflow-name-input"
          value={workflowName}
          onChange={e => setWorkflowName(e.target.value)}
        />
        <div className="workflow-actions">
          <button className="btn btn-sm" onClick={() => setShowPalette(p => !p)}>
            {showPalette ? 'Hide' : 'Show'} Nodes
          </button>
          <button className="btn btn-sm" onClick={executeWorkflow} disabled={isExecuting || nodes.length === 0}>
            {isExecuting ? '⏳ Running...' : '▶ Execute'}
          </button>
          <button className="btn btn-sm" onClick={exportWorkflow} disabled={nodes.length === 0}>Export</button>
          <label className="btn btn-sm" style={{ cursor: 'pointer' }}>
            Import <input type="file" accept=".json" onChange={importWorkflow} hidden />
          </label>
          <button className="btn btn-sm btn-danger" onClick={() => { setNodes([]); setEdges([]); setSelectedNode(null); setExecutionLog([]); }}>
            Clear
          </button>
        </div>
      </div>

      <div className="workflow-main">
        {/* Node Palette */}
        {showPalette && (
          <div className="workflow-palette">
            <div className="palette-title">Node Types</div>
            {Object.entries(NODE_TYPES).map(([type, config]) => (
              <button
                key={type}
                className="palette-item"
                onClick={() => addNode(type)}
                style={{ borderLeftColor: config.color }}
              >
                <span className="palette-icon">{config.icon}</span>
                <div>
                  <div className="palette-label">{config.label}</div>
                  <div className="palette-desc">{config.description}</div>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Canvas */}
        <div
          ref={canvasRef}
          className="workflow-canvas"
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onClick={() => setSelectedNode(null)}
        >
          {/* SVG edges */}
          <svg className="workflow-edges-svg">
            {edges.map(edge => {
              const from = nodes.find(n => n.id === edge.from);
              const to = nodes.find(n => n.id === edge.to);
              if (!from || !to) return null;
              const x1 = from.x + 90, y1 = from.y + 30;
              const x2 = to.x + 90, y2 = to.y + 30;
              const mx = (x1 + x2) / 2;
              return (
                <g key={edge.id}>
                  <path
                    d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                    fill="none" stroke="#64748b" strokeWidth="2"
                    markerEnd="url(#arrowhead)"
                  />
                </g>
              );
            })}
            <defs>
              <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />
              </marker>
            </defs>
          </svg>

          {/* Nodes */}
          {nodes.map(node => (
            <div
              key={node.id}
              className={`workflow-node ${selectedNode === node.id ? 'selected' : ''}`}
              style={{ left: node.x, top: node.y, borderColor: node.color }}
              onMouseDown={e => { e.stopPropagation(); handleMouseDown(e, node.id); }}
            >
              <div className="node-header" style={{ backgroundColor: node.color }}>
                <span className="node-icon">{node.icon}</span>
                <span className="node-label">{node.label}</span>
              </div>
              <div className="node-body">
                <button
                  className="node-connect-btn"
                  onMouseDown={e => startConnection(node.id, e)}
                  title="Drag to connect"
                >
                  {connecting === node.id ? '🔗 ...' : '⊕'}
                </button>
                <button
                  className="node-delete-btn"
                  onClick={(e) => { e.stopPropagation(); deleteNode(node.id); }}
                >
                  ✕
                </button>
              </div>
            </div>
          ))}

          {nodes.length === 0 && (
            <div className="canvas-empty">
              <div className="empty-icon">◈</div>
              <div>Click a node type from the palette to start building your workflow</div>
            </div>
          )}
        </div>

        {/* Node Config Panel */}
        {selectedNodeData && (
          <div className="workflow-config">
            <div className="config-title">
              <span>{selectedNodeData.icon} {selectedNodeData.label}</span>
              <button className="btn-sm" onClick={() => setSelectedNode(null)}>✕</button>
            </div>
            <div className="config-fields">
              {selectedNodeData.type === 'search' && (
                <>
                  <label>Query</label>
                  <input
                    value={selectedNodeData.config.query || ''}
                    onChange={e => updateNodeConfig(selectedNodeData.id, 'query', e.target.value)}
                    placeholder="Enter search query..."
                  />
                  <label>Max Results</label>
                  <input
                    type="number" min="1" max="20"
                    value={selectedNodeData.config.maxResults || 5}
                    onChange={e => updateNodeConfig(selectedNodeData.id, 'maxResults', parseInt(e.target.value))}
                  />
                  <label>Depth</label>
                  <select
                    value={selectedNodeData.config.depth || 'standard'}
                    onChange={e => updateNodeConfig(selectedNodeData.id, 'depth', e.target.value)}
                  >
                    <option value="surface">Surface</option>
                    <option value="standard">Standard</option>
                    <option value="deep">Deep</option>
                    <option value="exhaustive">Exhaustive</option>
                  </select>
                </>
              )}
              {selectedNodeData.type === 'export' && (
                <>
                  <label>Format</label>
                  <select
                    value={selectedNodeData.config.format || 'pdf'}
                    onChange={e => updateNodeConfig(selectedNodeData.id, 'format', e.target.value)}
                  >
                    <option value="pdf">PDF</option>
                    <option value="docx">DOCX</option>
                    <option value="pptx">PPTX</option>
                    <option value="md">Markdown</option>
                  </select>
                </>
              )}
              {selectedNodeData.type === 'condition' && (
                <>
                  <label>Condition</label>
                  <input
                    value={selectedNodeData.config.condition || ''}
                    onChange={e => updateNodeConfig(selectedNodeData.id, 'condition', e.target.value)}
                    placeholder="e.g., results.length > 3"
                  />
                </>
              )}
              {(selectedNodeData.type === 'analyze' || selectedNodeData.type === 'synthesize') && (
                <>
                  <label>Instructions</label>
                  <textarea
                    value={selectedNodeData.config.instructions || ''}
                    onChange={e => updateNodeConfig(selectedNodeData.id, 'instructions', e.target.value)}
                    placeholder="Describe what to analyze..."
                    rows={4}
                  />
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Execution Log */}
      {executionLog.length > 0 && (
        <div className="workflow-log">
          <div className="log-title">Execution Log</div>
          {executionLog.map((log, i) => (
            <div key={i} className={`log-entry ${log.status}`}>
              <span className="log-status">{log.status === 'running' ? '⏳' : '✓'}</span>
              <span className="log-label">{log.label}</span>
              <span className="log-time">{log.time}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Topological sort helper ---
function topologicalSort(nodes, edges) {
  const graph = new Map();
  const inDegree = new Map();
  nodes.forEach(n => { graph.set(n.id, []); inDegree.set(n.id, 0); });
  edges.forEach(e => {
    if (graph.has(e.from)) graph.get(e.from).push(e.to);
    if (inDegree.has(e.to)) inDegree.set(e.to, inDegree.get(e.to) + 1);
  });
  const queue = [...inDegree.entries()].filter(([, d]) => d === 0).map(([id]) => id);
  const sorted = [];
  while (queue.length) {
    const id = queue.shift();
    sorted.push(id);
    (graph.get(id) || []).forEach(next => {
      inDegree.set(next, inDegree.get(next) - 1);
      if (inDegree.get(next) === 0) queue.push(next);
    });
  }
  // Add any remaining nodes (cycles) at the end
  nodes.forEach(n => { if (!sorted.includes(n.id)) sorted.push(n.id); });
  return sorted;
}
