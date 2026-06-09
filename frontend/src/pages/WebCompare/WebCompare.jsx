import { useState, useEffect, useCallback } from 'react';
import './WebCompare.css';

// =============================================================================
// Multi-Webpage Compare & Tag — Phase 3
// =============================================================================
// Compare content from multiple webpages collected via the Chrome extension.
// Auto-tag pages, highlight differences, and generate comparison summaries.
// =============================================================================

export default function WebCompare() {
  const [pages, setPages] = useState([]);
  const [selectedPages, setSelectedPages] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [view, setView] = useState('list'); // list | compare | tags
  const [tagFilter, setTagFilter] = useState('');
  const [newTag, setNewTag] = useState('');

  // Fetch collected pages from backend
  useEffect(() => {
    fetchPages();
  }, []);

  async function fetchPages() {
    try {
      const res = await fetch('/api/context/collected-pages');
      if (res.ok) {
        const data = await res.json();
        setPages(data.pages || []);
      }
    } catch (e) {
      // Use demo data for development
      setPages(getDemoData());
    }
  }

  // Toggle page selection for comparison
  const togglePageSelection = useCallback((url) => {
    setSelectedPages(prev =>
      prev.includes(url)
        ? prev.filter(u => u !== url)
        : prev.length < 5 ? [...prev, url] : prev
    );
  }, []);

  // Run comparison
  const runComparison = useCallback(async () => {
    if (selectedPages.length < 2) return;
    setIsLoading(true);
    try {
      const res = await fetch('/api/context/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls: selectedPages }),
      });
      if (res.ok) {
        setComparison(await res.json());
      } else {
        setComparison(generateLocalComparison());
      }
    } catch {
      setComparison(generateLocalComparison());
    }
    setIsLoading(false);
    setView('compare');
  }, [selectedPages, pages]);

  // Generate local comparison from selected pages
  function generateLocalComparison() {
    const selected = pages.filter(p => selectedPages.includes(p.url));
    if (selected.length < 2) return null;

    const allTags = {};
    selected.forEach(p => {
      (p.tags || []).forEach(tag => {
        allTags[tag] = (allTags[tag] || 0) + 1;
      });
    });

    const commonTags = Object.entries(allTags)
      .filter(([_, count]) => count >= 2)
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count);

    return {
      pages: selected,
      commonTags,
      uniqueTags: Object.entries(allTags)
        .filter(([_, count]) => count === 1)
        .map(([tag]) => tag),
      summary: {
        pageCount: selected.length,
        domains: [...new Set(selected.map(p => new URL(p.url).hostname))],
        totalWordCount: selected.reduce((s, p) => s + (p.wordCount || 0), 0),
        avgWordCount: Math.round(selected.reduce((s, p) => s + (p.wordCount || 0), 0) / selected.length),
        pageTypes: [...new Set(selected.map(p => p.pageType || 'general'))],
      },
    };
  }

  // Add tag to a page
  const addTagToPage = useCallback((url, tag) => {
    if (!tag.trim()) return;
    setPages(prev => prev.map(p =>
      p.url === url
        ? { ...p, tags: [...new Set([...(p.tags || []), tag.trim().toLowerCase()])] }
        : p
    ));
    setNewTag('');
  }, []);

  // Remove tag from a page
  const removeTagFromPage = useCallback((url, tag) => {
    setPages(prev => prev.map(p =>
      p.url === url
        ? { ...p, tags: (p.tags || []).filter(t => t !== tag) }
        : p
    ));
  }, []);

  // Get all unique tags
  const allTags = [...new Set(pages.flatMap(p => p.tags || []))];

  // Filter pages by tag
  const filteredPages = tagFilter
    ? pages.filter(p => (p.tags || []).includes(tagFilter))
    : pages;

  // --- Render ---
  return (
    <div className="webcompare-page">
      {/* Header */}
      <div className="webcompare-header">
        <div>
          <h1>Web Page Compare & Tag</h1>
          <p className="header-subtitle">
            Collect pages via the Chrome extension, then compare and tag them here.
          </p>
        </div>
        <div className="header-actions">
          <button className="btn" onClick={fetchPages}>↻ Refresh</button>
          <button
            className="btn btn-primary"
            onClick={runComparison}
            disabled={selectedPages.length < 2 || isLoading}
          >
            {isLoading ? 'Comparing...' : `Compare (${selectedPages.length})`}
          </button>
        </div>
      </div>

      {/* View tabs */}
      <div className="view-tabs">
        <button className={`tab ${view === 'list' ? 'active' : ''}`} onClick={() => setView('list')}>
          Pages ({pages.length})
        </button>
        <button className={`tab ${view === 'compare' ? 'active' : ''}`} onClick={() => setView('compare')}
          disabled={!comparison}>
          Comparison
        </button>
        <button className={`tab ${view === 'tags' ? 'active' : ''}`} onClick={() => setView('tags')}>
          Tags ({allTags.length})
        </button>
      </div>

      {/* List View */}
      {view === 'list' && (
        <div className="page-list">
          {filteredPages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">📄</div>
              <p>No pages collected yet. Use the Chrome extension to collect pages for comparison.</p>
            </div>
          ) : (
            filteredPages.map(page => (
              <div key={page.url} className={`page-card ${selectedPages.includes(page.url) ? 'selected' : ''}`}>
                <div className="page-card-header">
                  <input
                    type="checkbox"
                    checked={selectedPages.includes(page.url)}
                    onChange={() => togglePageSelection(page.url)}
                  />
                  <div className="page-info">
                    <h3>{page.title || 'Untitled'}</h3>
                    <a href={page.url} target="_blank" rel="noreferrer" className="page-url">
                      {new URL(page.url).hostname} →
                    </a>
                  </div>
                  <span className={`page-type-badge ${page.pageType || 'general'}`}>
                    {page.pageType || 'general'}
                  </span>
                </div>
                {page.description && <p className="page-desc">{page.description.substring(0, 200)}</p>}
                <div className="page-meta">
                  <span>{page.wordCount?.toLocaleString() || '?'} words</span>
                  <span>{page.headings?.length || 0} headings</span>
                  <span>{page.externalLinks?.length || 0} links</span>
                </div>
                <div className="page-tags">
                  {(page.tags || []).map(tag => (
                    <span key={tag} className="tag-chip">
                      {tag}
                      <button onClick={() => removeTagFromPage(page.url, tag)}>×</button>
                    </span>
                  ))}
                  <div className="add-tag-inline">
                    <input
                      placeholder="+ tag"
                      value={newTag}
                      onChange={e => setNewTag(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') { addTagToPage(page.url, newTag); setNewTag(''); }}}
                    />
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Comparison View */}
      {view === 'compare' && comparison && (
        <div className="comparison-view">
          {/* Summary stats */}
          <div className="comparison-stats">
            <div className="stat-card">
              <div className="stat-value">{comparison.summary?.pageCount}</div>
              <div className="stat-label">Pages</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{comparison.summary?.domains?.length}</div>
              <div className="stat-label">Domains</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{comparison.summary?.totalWordCount?.toLocaleString()}</div>
              <div className="stat-label">Total Words</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{comparison.summary?.avgWordCount?.toLocaleString()}</div>
              <div className="stat-label">Avg Words</div>
            </div>
          </div>

          {/* Common tags */}
          <div className="comparison-section">
            <h3>Common Tags</h3>
            <div className="tag-cloud">
              {comparison.commonTags?.length > 0 ? comparison.commonTags.map(({ tag, count }) => (
                <span key={tag} className="tag-chip large" style={{ fontSize: `${12 + count * 2}px` }}>
                  {tag} <span className="tag-count">({count})</span>
                </span>
              )) : <p className="muted">No common tags found</p>}
            </div>
          </div>

          {/* Side-by-side comparison */}
          <div className="comparison-section">
            <h3>Side-by-Side</h3>
            <div className="compare-grid" style={{ gridTemplateColumns: `repeat(${comparison.pages?.length || 2}, 1fr)` }}>
              {comparison.pages?.map(page => (
                <div key={page.url} className="compare-column">
                  <h4>{page.title?.substring(0, 60) || 'Untitled'}</h4>
                  <div className="compare-domain">{new URL(page.url).hostname}</div>
                  <div className="compare-details">
                    <div><strong>Words:</strong> {page.wordCount?.toLocaleString()}</div>
                    <div><strong>Type:</strong> {page.pageType || 'general'}</div>
                    <div><strong>Headings:</strong> {page.headings?.length || 0}</div>
                  </div>
                  {page.headings?.length > 0 && (
                    <div className="compare-headings">
                      <strong>Structure:</strong>
                      <ul>
                        {page.headings.slice(0, 5).map((h, i) => (
                          <li key={i} className={`heading-level-${h.level}`}>{h.text?.substring(0, 60)}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tags View */}
      {view === 'tags' && (
        <div className="tags-view">
          <div className="tag-filter-bar">
            <input
              placeholder="Filter by tag..."
              value={tagFilter}
              onChange={e => setTagFilter(e.target.value)}
            />
            {tagFilter && <button className="btn-sm" onClick={() => setTagFilter('')}>Clear</button>}
          </div>
          <div className="all-tags">
            {allTags.length === 0 ? (
              <p className="muted">No tags yet. Add tags to pages in the list view.</p>
            ) : (
              allTags.map(tag => {
                const count = pages.filter(p => (p.tags || []).includes(tag)).length;
                return (
                  <button
                    key={tag}
                    className={`tag-chip large ${tagFilter === tag ? 'active' : ''}`}
                    onClick={() => { setTagFilter(tag); setView('list'); }}
                  >
                    {tag} <span className="tag-count">({count})</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Demo data for development
function getDemoData() {
  return [
    {
      url: 'https://arxiv.org/abs/2401.12345',
      title: 'Attention Is All You Need — Revisited',
      description: 'A comprehensive review of transformer architectures and their impact on modern NLP research.',
      pageType: 'academic',
      wordCount: 4500,
      headings: [
        { level: 1, text: 'Abstract' },
        { level: 2, text: 'Introduction' },
        { level: 2, text: 'Background' },
      ],
      tags: ['ai-ml', 'research', 'transformers'],
      externalLinks: [],
    },
    {
      url: 'https://techcrunch.com/2024/ai-startup-funding',
      title: 'AI Startup Funding Hits Record High in 2024',
      description: 'Venture capital investment in AI companies reaches unprecedented levels as enterprise adoption accelerates.',
      pageType: 'news',
      wordCount: 1800,
      headings: [
        { level: 1, text: 'AI Funding Surges' },
        { level: 2, text: 'Enterprise Leaders' },
      ],
      tags: ['business', 'ai-ml', 'news'],
      externalLinks: [],
    },
    {
      url: 'https://medium.com/@researcher/rag-vs-fine-tuning-2024',
      title: 'RAG vs Fine-Tuning: When to Use What',
      description: 'A practical guide to choosing between retrieval-augmented generation and fine-tuning for LLM applications.',
      pageType: 'article',
      wordCount: 3200,
      headings: [
        { level: 1, text: 'Introduction' },
        { level: 2, text: 'RAG Overview' },
        { level: 2, text: 'Fine-Tuning Overview' },
        { level: 2, text: 'Decision Framework' },
      ],
      tags: ['ai-ml', 'technology', 'research'],
      externalLinks: [],
    },
  ];
}
