/**
 * ResearchSteps — Perplexity-style step-by-step agent trace UI.
 *
 * Groups WebSocket events (thinking, tool_call, tool_result, status) into
 * numbered research steps with expandable details, per-step sources,
 * and duration tracking.
 */
import { useState, useMemo, useEffect, useRef } from 'react';
import './ResearchSteps.css';

// ─── Tool Metadata ────────────────────────────────────────────────────────────
const TOOL_META = {
  tavily_search:          { icon: '🔍', label: 'Web Search' },
  brave_search:           { icon: '🔍', label: 'Web Search' },
  exa_search:             { icon: '🔍', label: 'Semantic Search' },
  arxiv_search:           { icon: '📚', label: 'Academic Search' },
  scholar_search:         { icon: '🎓', label: 'Scholar Search' },
  scrape_webpage:         { icon: '🌐', label: 'Read Webpage' },
  fetch_url:              { icon: '🌐', label: 'Fetch URL' },
  analyze_image:          { icon: '👁️', label: 'Analyze Image' },
  write_file:             { icon: '📝', label: 'Write Report' },
  read_file:              { icon: '📖', label: 'Read File' },
  self_reflect:           { icon: '🪞', label: 'Self-Reflect' },
  evaluate_confidence:    { icon: '📊', label: 'Evaluate Confidence' },
  generate_hypothesis:    { icon: '💡', label: 'Generate Hypothesis' },
  spawn_subagent:         { icon: '🤖', label: 'Spawn Sub-agent' },
  write_todos:            { icon: '✅', label: 'Update Plan' },
  get_todos:              { icon: '📋', label: 'Read Plan' },
  knowledge_graph_add:    { icon: '🕸️', label: 'Update Knowledge Graph' },
  knowledge_graph_query:  { icon: '🕸️', label: 'Query Knowledge Graph' },
  debate:                 { icon: '⚔️', label: 'Debate' },
  synthesize:             { icon: '🧬', label: 'Synthesize' },
  run_experiment:         { icon: '🧪', label: 'Run Experiment' },
  code_execute:           { icon: '▶️', label: 'Execute Code' },
};

const DEFAULT_META = { icon: '🔧', label: 'Tool Call' };

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Extract URLs from a tool result string. */
function extractUrlsFromResult(result) {
  if (!result) return [];
  const urlRegex = /https?:\/\/[^\s\])"',]+/g;
  const urls = (String(result).match(urlRegex) || []);
  const seen = new Set();
  return urls
    .map(u => u.replace(/[.,;)}\]]+$/, ''))
    .filter(u => {
      if (seen.has(u) || u.length > 200) return false;
      seen.add(u);
      return true;
    })
    .slice(0, 8)
    .map(url => {
      try {
        return { url, domain: new URL(url).hostname.replace('www.', '') };
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

/** Get a human-readable title for a step. */
function getStepTitle(step) {
  if (step.type === 'thinking') return step.thinkingText || 'Reasoning...';
  if (step.type === 'status')    return step.statusMessage || 'Processing...';

  const meta = TOOL_META[step.toolName] || DEFAULT_META;
  const query = step.searchQuery;
  if (query) return `${meta.label}: "${query.length > 80 ? query.slice(0, 80) + '…' : query}"`;
  return meta.label;
}

/** Get icon for a step. */
function getStepIcon(step) {
  if (step.type === 'thinking') return '💭';
  if (step.type === 'status')   return '📡';
  return (TOOL_META[step.toolName] || DEFAULT_META).icon;
}

// ─── Main Component ───────────────────────────────────────────────────────────

/**
 * Props:
 *   events     — Array of WebSocket events (thinking, tool_call, tool_result, status)
 *   isRunning  — Boolean, is research still in progress
 *   defaultExpanded — Whether to start expanded (default true)
 */
export default function ResearchSteps({ events, isRunning, defaultExpanded = true }) {
  const [expandedSteps, setExpandedSteps] = useState({});
  const [isCollapsed, setIsCollapsed] = useState(!defaultExpanded);
  const endRef = useRef(null);

  // Auto-scroll to newest step while running
  useEffect(() => {
    if (!isCollapsed && isRunning) {
      endRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events, isCollapsed, isRunning]);

  // ─── Group events into steps ────────────────────────────────────────────────
  const steps = useMemo(() => {
    const result = [];
    let currentStep = null;
    let stepIndex = 0;

    for (const ev of events) {
      // thinking event → start a new reasoning step
      if (ev.type === 'thinking') {
        if (currentStep) result.push(currentStep);
        stepIndex++;
        currentStep = {
          index: stepIndex,
          type: 'thinking',
          thinkingText: ev.data?.message || '',
          toolCalls: [],
          sources: [],
          startTime: ev.timestamp,
          duration: null,
          status: 'running',
        };
        continue;
      }

      // status event → progress update step
      if (ev.type === 'status') {
        if (currentStep) result.push(currentStep);
        stepIndex++;
        currentStep = {
          index: stepIndex,
          type: 'status',
          statusMessage: ev.data?.message || ev.data?.status || '',
          toolCalls: [],
          sources: [],
          startTime: ev.timestamp,
          duration: null,
          status: 'complete',
        };
        continue;
      }

      // tool_call → new tool step
      if (ev.type === 'tool_call') {
        if (currentStep) result.push(currentStep);
        stepIndex++;
        currentStep = {
          index: stepIndex,
          type: 'tool_call',
          toolName: ev.data?.tool || 'unknown',
          searchQuery: ev.data?.input?.query || ev.data?.input?.url || '',
          input: ev.data?.input || {},
          result: null,
          resultLength: 0,
          sources: [],
          startTime: ev.timestamp,
          duration: null,
          status: 'running',
        };
        continue;
      }

      // tool_result → attach to current step if it matches, or last tool step
      if (ev.type === 'tool_result') {
        if (currentStep && currentStep.type === 'tool_call' && !currentStep.result) {
          const resultText = String(ev.data?.result || '');
          currentStep.result = resultText;
          currentStep.resultLength = resultText.length;
          currentStep.sources = extractUrlsFromResult(resultText);
          currentStep.endTime = ev.timestamp;
          currentStep.duration = currentStep.startTime
            ? Math.round((ev.timestamp - currentStep.startTime) / 1000)
            : null;
          currentStep.status = 'complete';
        }
        continue;
      }
    }

    if (currentStep) result.push(currentStep);
    return result;
  }, [events]);

  const completedSteps = steps.filter(s => s.status === 'complete').length;
  const totalSteps = steps.length;

  // ─── Toggle individual step ─────────────────────────────────────────────────
  const toggleStep = (idx) => {
    setExpandedSteps(prev => ({ ...prev, [idx]: !prev[idx] }));
  };

  // ─── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="research-steps-container">
      {/* Header */}
      <button className="rs-header" onClick={() => setIsCollapsed(!isCollapsed)}>
        <div className="rs-header-left">
          <svg
            className={`rs-chevron ${isCollapsed ? '' : 'rs-chevron-open'}`}
            width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>
          <span className="rs-title">Research Steps</span>
          <span className="rs-step-count">
            {completedSteps} / {totalSteps} steps
          </span>
        </div>
        {isRunning && (
          <div className="rs-live-badge">
            <span className="rs-live-dot" />
            <span>Live</span>
          </div>
        )}
      </button>

      {/* Steps body */}
      {!isCollapsed && steps.length > 0 && (
        <div className="rs-body">
          {steps.map((step) => {
            const icon = getStepIcon(step);
            const title = getStepTitle(step);
            const isExpanded = expandedSteps[step.index] ?? false;
            const hasDetails = step.result || step.sources.length > 0 ||
              (step.input && Object.keys(step.input).length > 0);

            return (
              <div key={step.index} className={`rs-step rs-step-${step.status}`}>
                {/* Timeline column */}
                <div className="rs-timeline">
                  <div className={`rs-step-number rs-status-${step.status}`}>
                    {step.status === 'complete' ? (
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    ) : step.status === 'running' ? (
                      <div className="rs-spinner" />
                    ) : (
                      <span>{step.index}</span>
                    )}
                  </div>
                  {step.index < totalSteps && <div className="rs-connector" />}
                </div>

                {/* Content column */}
                <div className="rs-content">
                  {/* Step header row */}
                  <div
                    className={`rs-step-header ${hasDetails ? 'rs-clickable' : ''}`}
                    onClick={() => hasDetails && toggleStep(step.index)}
                  >
                    <span className="rs-step-icon">{icon}</span>
                    <div className="rs-step-info">
                      <span className="rs-step-title">{title}</span>
                      <div className="rs-step-meta">
                        {step.duration != null && step.duration > 0 && (
                          <span className="rs-duration">{step.duration}s</span>
                        )}
                        {step.status === 'running' && isRunning && (
                          <span className="rs-running-text">Running...</span>
                        )}
                        {step.sources.length > 0 && (
                          <span className="rs-source-count">
                            {step.sources.length} source{step.sources.length > 1 ? 's' : ''}
                          </span>
                        )}
                        {step.type === 'tool_call' && step.resultLength > 0 && (
                          <span className="rs-result-size">
                            {step.resultLength > 1000
                              ? `${(step.resultLength / 1000).toFixed(1)}k`
                              : step.resultLength} chars
                          </span>
                        )}
                      </div>
                    </div>
                    {hasDetails && (
                      <svg
                        className={`rs-expand-chevron ${isExpanded ? 'rs-expand-open' : ''}`}
                        width="14" height="14" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                      >
                        <polyline points="6 9 12 15 18 9" />
                      </svg>
                    )}
                  </div>

                  {/* Sources strip (always visible if present) */}
                  {step.sources.length > 0 && !isExpanded && (
                    <div className="rs-sources-strip">
                      {step.sources.slice(0, 4).map((src, i) => (
                        <a
                          key={i}
                          href={src.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rs-source-chip"
                          onClick={e => e.stopPropagation()}
                        >
                          <img
                            src={`https://www.google.com/s2/favicons?domain=${src.domain}&sz=16`}
                            alt=""
                            className="rs-favicon"
                            onError={e => { e.target.style.display = 'none'; }}
                          />
                          <span>{src.domain}</span>
                        </a>
                      ))}
                      {step.sources.length > 4 && (
                        <span className="rs-more-chip">+{step.sources.length - 4}</span>
                      )}
                    </div>
                  )}

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="rs-details">
                      {/* Search query */}
                      {step.searchQuery && (
                        <div className="rs-detail-row">
                          <span className="rs-detail-label">Query</span>
                          <span className="rs-detail-value rs-query-text">"{step.searchQuery}"</span>
                        </div>
                      )}

                      {/* Tool input params (excluding query) */}
                      {step.input && Object.keys(step.input).length > 0 &&
                        Object.keys(step.input).filter(k => k !== 'query' && k !== 'url').length > 0 && (
                        <div className="rs-detail-row">
                          <span className="rs-detail-label">Parameters</span>
                          <code className="rs-detail-code">
                            {JSON.stringify(
                              Object.fromEntries(
                                Object.entries(step.input).filter(([k]) => k !== 'query' && k !== 'url')
                              ), null, 2
                            )}
                          </code>
                        </div>
                      )}

                      {/* Result preview */}
                      {step.result && (
                        <div className="rs-result-preview">
                          <div className="rs-result-header">Result Preview</div>
                          <div className="rs-result-text">
                            {step.result.slice(0, 500)}
                            {step.result.length > 500 && '…'}
                          </div>
                        </div>
                      )}

                      {/* Full source list */}
                      {step.sources.length > 0 && (
                        <div className="rs-detail-sources">
                          <div className="rs-detail-label">Sources ({step.sources.length})</div>
                          {step.sources.map((src, i) => (
                            <a
                              key={i}
                              href={src.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rs-source-link"
                            >
                              <img
                                src={`https://www.google.com/s2/favicons?domain=${src.domain}&sz=16`}
                                alt=""
                                className="rs-favicon"
                                onError={e => { e.target.style.display = 'none'; }}
                              />
                              <div className="rs-source-link-info">
                                <span className="rs-source-link-domain">{src.domain}</span>
                                <span className="rs-source-link-url">
                                  {src.url.length > 70 ? src.url.slice(0, 70) + '…' : src.url}
                                </span>
                              </div>
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                                stroke="currentColor" strokeWidth="2" className="rs-link-arrow">
                                <polyline points="7 17 17 7" />
                                <polyline points="7 7 17 7 17 17" />
                              </svg>
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          <div ref={endRef} />

          {/* Running indicator at bottom */}
          {isRunning && steps.length > 0 && steps[steps.length - 1].status !== 'running' && (
            <div className="rs-pending-next">
              <div className="rs-timeline">
                <div className="rs-step-number rs-status-pending">
                  <span>{totalSteps + 1}</span>
                </div>
              </div>
              <div className="rs-content">
                <div className="rs-pending-text">Waiting for next step...</div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!isCollapsed && steps.length === 0 && isRunning && (
        <div className="rs-body rs-empty">
          <div className="rs-spinner-lg" />
          <span>Initializing research pipeline...</span>
        </div>
      )}
    </div>
  );
}
