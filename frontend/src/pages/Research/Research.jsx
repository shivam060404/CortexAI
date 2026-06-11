import { useState, useRef, useEffect } from 'react';
import { ResearchWebSocket } from '../../services/websocket';
import { createSession, submitFeedback, alignQuery } from '../../services/api';
import { marked } from 'marked';
import ReportViewer from '../../components/ReportViewer/ReportViewer';
import ImageDropzone from '../../components/ImageDropzone/ImageDropzone';
import LivePlanEditor from '../../components/LivePlanEditor/LivePlanEditor';
import TaggingSystem from '../../components/TaggingSystem/TaggingSystem';
import DocumentUploader from '../../components/DocumentUploader/DocumentUploader';
import './Research.css';

// Parse sources from tool results
function extractSources(events) {
  const sources = [];
  const seen = new Set();
  events.forEach(ev => {
    if (ev.type === 'tool_result' && ev.data?.result) {
      const urlRegex = /https?:\/\/[^\s\])"',]+/g;
      const urls = ev.data.result.match(urlRegex) || [];
      urls.forEach(url => {
        try {
          const clean = url.replace(/[.,;)}\]]+$/, '');
          if (!seen.has(clean) && clean.length < 200) {
            seen.add(clean);
            const hostname = new URL(clean).hostname.replace('www.', '');
            sources.push({ url: clean, domain: hostname, title: hostname });
          }
        } catch {}
      });
    }
  });
  return sources;
}

// Inject citation numbers into markdown content
function injectCitations(content, sources) {
  if (!sources.length || !content) return content;
  let result = content;
  sources.forEach((src, i) => {
    const num = `[${i + 1}]`;
    if (result.includes(src.url)) {
      result = result.replace(src.url, `[${src.domain}](${src.url}) ${num}`);
    }
  });
  return result;
}

const PHASE_ORDER = ['Initializing', 'Planning', 'Searching', 'Analyzing', 'Reflecting', 'Writing', 'Complete'];

function getPhase(events, status) {
  if (status === 'idle') return null;
  if (status === 'connecting') return 0;
  if (status === 'completed') return 6;

  const toolNames = events.filter(e => e.type === 'tool_call').map(e => e.data?.tool || '');
  if (toolNames.some(t => t.includes('write_file'))) return 5;
  if (toolNames.some(t => t.includes('self_reflect'))) return 4;
  if (toolNames.some(t => t.includes('evaluate') || t.includes('hypothesis') || t.includes('subagent'))) return 3;
  if (toolNames.some(t => t.includes('search'))) return 2;
  if (toolNames.some(t => t.includes('todos'))) return 1;
  if (events.length > 0) return 1;
  return 0;
}

const EXAMPLE_QUERIES = [
  "Compare transformer architectures vs state space models for long-context tasks",
  "Impact of quantum computing on modern cryptography — timeline and risks",
  "How are leading biotech companies using AI for drug discovery in 2026?",
  "Analyze the economic effects of universal basic income — real-world case studies",
];

export default function Research() {
  const [query, setQuery] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [events, setEvents] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [todos, setTodos] = useState([]);
  const [status, setStatus] = useState('idle');
  const [finalReport, setFinalReport] = useState('');
  const [showThinking, setShowThinking] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const [researchMode, setResearchMode] = useState('deep');
  const [feedbackSent, setFeedbackSent] = useState(false);
  const [feedbackComment, setFeedbackComment] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);
  const [clarificationData, setClarificationData] = useState(null);
  const [clarificationInput, setClarificationInput] = useState('');
  
  // New State for Phase 7
  const [queryTags, setQueryTags] = useState([]);
  const [queryImage, setQueryImage] = useState(null);
  const [queryImageName, setQueryImageName] = useState('');
  const [attachedFiles, setAttachedFiles] = useState([]);

  const timerRef = useRef(null);
  const eventsEndRef = useRef(null);
  const wsRef = useRef(null);
  const inputRef = useRef(null);

  // Auto scroll thinking panel
  useEffect(() => {
    if (showThinking) eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events, showThinking]);

  // Timer
  useEffect(() => {
    if (status === 'running') {
      timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
  }, [status]);

  // Extract final report from message events
  useEffect(() => {
    const msgEvents = events.filter(e => e.type === 'message' && e.data?.content);
    if (msgEvents.length > 0) {
      const last = msgEvents[msgEvents.length - 1];
      if (last.data.content.length > 200) {
        setFinalReport(last.data.content);
      }
    }
  }, [events]);

  const startResearch = async (q) => {
    const searchQuery = q || query;
    if (!searchQuery.trim() || status === 'running') return;

    setQuery(searchQuery);
    setStatus('connecting');
    setEvents([]);
    setMetrics(null);
    setTodos([]);
    setFinalReport('');
    setElapsed(0);
    setFeedbackSent(false);
    setShowFeedback(false);
    setFeedbackComment('');

    try {
      // 1. Pre-execution Alignment Check (Clarification Loop)
      const alignRes = await alignQuery(searchQuery, researchMode);
      if (alignRes.needs_clarification) {
        setClarificationData(alignRes);
        setStatus('clarifying');
        return; // Pause execution and wait for user
      }

      // If no clarification needed, proceed directly to WS
      await startWebSocket(searchQuery, researchMode);
    } catch (err) {
      setStatus('error');
      setEvents(prev => [...prev, { type: 'error', data: { message: err.message }, timestamp: Date.now() }]);
    }
  };

  const startWebSocket = async (finalQuery, mode) => {
    try {
      const session = await createSession(finalQuery);
      setSessionId(session.id);

      const ws = new ResearchWebSocket(session.id, {
        onOpen: () => {
          setStatus('running');
          // Include tags, image, and attached files
          ws.send(JSON.stringify({ 
            query: finalQuery, 
            mode: mode,
            tags: queryTags,
            image_data: queryImage,
            attached_files: attachedFiles.map(f => ({
              filename: f.filename,
              text: f.text,
              image_data: f.image_data,
              file_type: f.file_type,
            })),
          }));
        },
        onEvent: (event) => {
          setEvents(prev => [...prev, { ...event, timestamp: Date.now() }]);
        },
        onMetrics: (data) => setMetrics(data),
        onTodoUpdate: (data) => setTodos(data.todos || []),
        onComplete: () => setStatus('completed'),
        onError: (data) => {
          setEvents(prev => [...prev, { type: 'error', data, timestamp: Date.now() }]);
        },
        onClose: () => {
          if (status === 'running') setStatus('completed');
        },
      });

      wsRef.current = ws;
      ws.connect();
    } catch (err) {
      setStatus('error');
      setEvents(prev => [...prev, { type: 'error', data: { message: err.message }, timestamp: Date.now() }]);
    }
  };

  const handeClarificationSubmit = (answer) => {
    if (!answer.trim()) return;
    const expandedQuery = `${query}\n\n[USER CLARIFICATION]\n${answer}`;
    setQuery(expandedQuery);
    setStatus('connecting');
    startWebSocket(expandedQuery, researchMode);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      startResearch();
    }
  };

  const sources = extractSources(events);
  const currentPhase = getPhase(events, status);
  const toolCallCount = events.filter(e => e.type === 'tool_call').length;
  const searchCount = events.filter(e => e.type === 'tool_call' && e.data?.tool?.includes('search')).length;
  const thinkingEvents = events.filter(e => ['thinking', 'tool_call', 'tool_result', 'status'].includes(e.type));
  const reportHtml = finalReport ? marked.parse(injectCitations(finalReport, sources)) : '';
  const charts = events.filter(e => e.type === 'chart_data').map(e => e.data);

  // ─── IDLE STATE: Perplexity-style centered input ───
  if (status === 'idle') {
    return (
      <div className="research-landing">
        <div className="landing-content">
          <div className="landing-logo">◈</div>
          <h1 className="landing-title">What do you want to research?</h1>
          <p className="landing-subtitle">
            CortexAI will autonomously plan, search, analyze, and write a comprehensive report
          </p>
          <div className="landing-input-wrap">
            <textarea
              ref={inputRef}
              className="landing-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything — CortexAI will handle the rest..."
              rows={1}
              id="research-query-input"
              autoFocus
            />
            <button
              className="landing-submit"
              onClick={() => startResearch()}
              disabled={!query.trim() && !queryImage}
              id="start-research-btn"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
            </button>
          </div>
          
          <div className="advanced-inputs">
            <TaggingSystem tags={queryTags} onTagsChange={setQueryTags} />
            <ImageDropzone onImageDrop={(data, name) => {
              setQueryImage(data);
              setQueryImageName(name);
            }} />
            <DocumentUploader
              onFilesReady={(results) => setAttachedFiles(prev => [...prev, ...results])}
              sessionId={sessionId || 'default'}
              maxFiles={5}
            />
            {queryImage && (
              <div className="image-preview">
                <span className="image-name">📎 {queryImageName}</span>
                <button className="remove-image" onClick={() => { setQueryImage(null); setQueryImageName(''); }}>×</button>
              </div>
            )}
          </div>

          {/* Research Mode Selector */}
          <div className="mode-selector">
            {[
              { id: 'fast', icon: '⚡', label: 'Fast', desc: 'Quick overview, 3-5 sources' },
              { id: 'deep', icon: '🧠', label: 'Deep', desc: 'Comprehensive, 15-20 sources' },
              { id: 'academic', icon: '🔬', label: 'Academic', desc: 'Scholarly, peer-reviewed focus' },
            ].map(m => (
              <button
                key={m.id}
                className={`mode-btn ${researchMode === m.id ? 'mode-active' : ''}`}
                onClick={() => setResearchMode(m.id)}
              >
                <span className="mode-icon">{m.icon}</span>
                <span className="mode-label">{m.label}</span>
                <span className="mode-desc">{m.desc}</span>
              </button>
            ))}
          </div>

          <div className="landing-suggestions">
            {EXAMPLE_QUERIES.map((q, i) => (
              <button 
                key={i} 
                className="suggestion-chip" 
                onClick={() => { setQuery(q); startResearch(q); }}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ─── CLARIFYING STATE: Interactive Reasoning ───
  if (status === 'clarifying' && clarificationData) {
    return (
      <div className="research-landing">
        <div className="landing-content clarification-content">
          <div className="clarification-icon">🤔</div>
          <h2 className="clarification-title">I need a bit more detail</h2>
          <p className="clarification-question">{clarificationData.question}</p>
          
          {clarificationData.suggestions && clarificationData.suggestions.length > 0 && (
            <div className="clarification-suggestions">
              {clarificationData.suggestions.map((sug, i) => (
                <button
                  key={i}
                  className="suggestion-chip"
                  onClick={() => {
                    setClarificationInput(sug);
                    handeClarificationSubmit(sug);
                  }}
                >
                  {sug}
                </button>
              ))}
            </div>
          )}

          <div className="clarification-input-wrap">
            <input
              className="followup-input"
              value={clarificationInput}
              onChange={(e) => setClarificationInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handeClarificationSubmit(clarificationInput);
              }}
              placeholder="Type your clarification..."
              autoFocus
            />
            <button
              className="btn btn-primary"
              onClick={() => handeClarificationSubmit(clarificationInput)}
              disabled={!clarificationInput.trim()}
            >Continue</button>
          </div>
        </div>
      </div>
    );
  }

  // ─── ACTIVE STATE: Research in progress / complete ───
  return (
    <div className="research-active">
      {/* Query Header */}
      <div className="research-query-header">
        <h2 className="research-query-text">{query}</h2>
        <div className="research-query-meta">
          {status === 'running' && <span className="research-timer">{Math.floor(elapsed / 60)}:{(elapsed % 60).toString().padStart(2, '0')}</span>}
          <span className={`research-status-badge status-${status}`}>
            {status === 'running' && <span className="pulse-dot" />}
            {status === 'running' ? 'Researching' : status === 'completed' ? 'Complete' : status}
          </span>
          {status === 'running' && (
            <button className="btn-stop" onClick={() => wsRef.current?.close()}>Stop</button>
          )}
        </div>
      </div>

      {/* Progress Phases */}
      {currentPhase !== null && (
        <div className="phase-bar">
          {PHASE_ORDER.map((phase, i) => (
            <div key={phase} className={`phase-step ${i < currentPhase ? 'done' : i === currentPhase ? 'active' : ''}`}>
              <div className="phase-dot">
                {i < currentPhase ? '✓' : i === currentPhase && status === 'running' ? <span className="mini-spinner" /> : ''}
              </div>
              <span className="phase-label">{phase}</span>
            </div>
          ))}
        </div>
      )}

      {/* Live Stats */}
      {(status === 'running' || status === 'completed') && (
        <div className="live-stats">
          <span>🔍 {searchCount} searches</span>
          <span>🔧 {toolCallCount} tool calls</span>
          <span>📄 {sources.length} sources found</span>
          {metrics && <span>📊 {(metrics.tokens_used || 0).toLocaleString()} tokens</span>}
        </div>
      )}

      {/* Main Content Area */}
      <div className="research-main">
        {/* Left: Thinking + Report */}
        <div className="research-left">
          {/* Collapsible Thinking Panel */}
          <div className="thinking-panel">
            <button className="thinking-toggle" onClick={() => setShowThinking(!showThinking)}>
              <span className="thinking-toggle-icon">{showThinking ? '▼' : '▶'}</span>
              <span>Thinking</span>
              <span className="thinking-count">{thinkingEvents.length} steps</span>
            </button>
            {showThinking && (
              <div className="thinking-stream">
                {thinkingEvents.map((ev, i) => (
                  <div key={i} className={`thinking-step step-${ev.type}`}>
                    <span className="step-icon">
                      {ev.type === 'thinking' ? '💭' : ev.type === 'tool_call' ? '🔧' : ev.type === 'tool_result' ? '📥' : '📡'}
                    </span>
                    <div className="step-content">
                      {ev.type === 'thinking' && <span className="step-text">{ev.data.message}</span>}
                      {ev.type === 'tool_call' && (
                        <span className="step-text">
                          <strong>{ev.data.tool}</strong>
                          {ev.data.input?.query && <span className="step-query"> — "{ev.data.input.query}"</span>}
                        </span>
                      )}
                      {ev.type === 'tool_result' && (
                        <span className="step-text step-result-text">
                          <strong>{ev.data.tool}</strong> returned {ev.data.result?.length || 0} chars
                        </span>
                      )}
                      {ev.type === 'status' && <span className="step-text">{ev.data.message}</span>}
                    </div>
                  </div>
                ))}
                <div ref={eventsEndRef} />
              </div>
            )}
          </div>

          {/* Research Plan (Todos) */}
          {todos.length > 0 && (
            <LivePlanEditor 
              todos={todos} 
              onUpdatePlan={(newTodos) => {
                setTodos(newTodos);
                // Send plan edit back to websocket to resume HITL or update agent context
                if (wsRef.current && status === 'running') {
                  wsRef.current.send(JSON.stringify({
                    type: 'hitl_resume',
                    data: {
                      action: 'update_plan',
                      modifications: { todos: newTodos }
                    }
                  }));
                }
              }} 
            />
          )}

          {/* Final Report */}
          {finalReport && (
            <ReportViewer 
              htmlContent={reportHtml} 
              charts={charts} 
              title={query.length > 50 ? query.substring(0, 50) + "..." : query}
              onExportPDF={() => { alert("Generating PDF... (MCP Backend will process this)"); }}
              onExportPPTX={() => { alert("Generating PPTX... (MCP Backend will process this)"); }}
              onExportHTML={() => { alert("Generating Interactive HTML... (MCP Backend will process this)"); }}
            />
          )}

          {/* Still researching indicator */}
          {status === 'running' && !finalReport && (
            <div className="researching-indicator">
              <div className="research-ripple"><div /><div /><div /></div>
              <p>Deep research in progress...</p>
              <p className="researching-sub">CortexAI is searching, analyzing, and synthesizing information</p>
            </div>
          )}
        </div>

        {/* Right: Sources Panel */}
        {sources.length > 0 && (
          <div className="sources-panel">
            <h4 className="sources-title">
              Sources
              <span className="sources-count">{sources.length}</span>
            </h4>
            <div className="sources-list">
              {sources.map((src, i) => (
                <a key={i} href={src.url} target="_blank" rel="noopener noreferrer" className="source-card">
                  <span className="source-num">{i + 1}</span>
                  <div className="source-info">
                    <span className="source-domain">{src.domain}</span>
                    <span className="source-url">{src.url.length > 60 ? src.url.slice(0, 60) + '...' : src.url}</span>
                  </div>
                  <svg className="source-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="7 17 17 7"/><polyline points="7 7 17 7 17 17"/></svg>
                </a>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* RLHF Feedback UI (after completion) */}
      {status === 'completed' && (
        <div className="followup-area">
          {/* Feedback Panel */}
          {!feedbackSent ? (
            <div className="feedback-panel">
              <span className="feedback-label">Was this research helpful?</span>
              <div className="feedback-actions">
                <button
                  className="feedback-btn feedback-up"
                  onClick={async () => {
                    if (sessionId) await submitFeedback(sessionId, 1, '', researchMode).catch(() => {});
                    setFeedbackSent(true);
                  }}
                >👍</button>
                <button
                  className="feedback-btn feedback-down"
                  onClick={() => setShowFeedback(true)}
                >👎</button>
              </div>
              {showFeedback && (
                <div className="feedback-detail">
                  <input
                    className="followup-input"
                    placeholder="What could be improved? (e.g., 'too shallow', 'more technical')"
                    value={feedbackComment}
                    onChange={(e) => setFeedbackComment(e.target.value)}
                    onKeyDown={async (e) => {
                      if (e.key === 'Enter' && feedbackComment.trim()) {
                        if (sessionId) await submitFeedback(sessionId, -1, feedbackComment, researchMode).catch(() => {});
                        setFeedbackSent(true);
                      }
                    }}
                  />
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={async () => {
                      if (sessionId) await submitFeedback(sessionId, -1, feedbackComment, researchMode).catch(() => {});
                      setFeedbackSent(true);
                    }}
                  >Submit</button>
                </div>
              )}
            </div>
          ) : (
            <div className="feedback-thanks">✅ Feedback recorded — CortexAI will learn from this</div>
          )}

          {/* Follow-up */}
          <div className="followup-wrap">
            <input
              className="followup-input"
              placeholder="Ask a follow-up question..."
              onKeyDown={(e) => {
                if (e.key === 'Enter' && e.target.value.trim()) {
                  setQuery(e.target.value);
                  setStatus('idle');
                  setTimeout(() => startResearch(e.target.value), 100);
                }
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
