// =============================================================================
// content.js — Enhanced Content Extraction with Auto-Detection
// =============================================================================
// Extracts page content, detects research-relevant pages, and supports
// multi-page tagging and comparison.
// =============================================================================

/**
 * Extract structured content from the current page.
 */
function extractContent() {
  const title = document.title;
  const url = window.location.href;

  // Meta tags
  const metaDesc = document.querySelector('meta[name="description"]')?.content || '';
  const metaKeywords = document.querySelector('meta[name="keywords"]')?.content || '';
  const metaAuthor = document.querySelector('meta[name="author"]')?.content || '';
  const ogTitle = document.querySelector('meta[property="og:title"]')?.content || '';
  const ogDesc = document.querySelector('meta[property="og:description"]')?.content || '';
  const publishedTime = document.querySelector('meta[property="article:published_time"]')?.content
    || document.querySelector('meta[name="date"]')?.content || '';

  // Structured data (JSON-LD)
  let structuredData = null;
  const jsonLd = document.querySelector('script[type="application/ld+json"]');
  if (jsonLd) {
    try {
      structuredData = JSON.parse(jsonLd.textContent);
    } catch (e) { /* ignore parse errors */ }
  }

  // Main content extraction (readability-like)
  const clone = document.body.cloneNode(true);
  const elementsToRemove = clone.querySelectorAll(
    'script, style, nav, header, footer, iframe, img, svg, aside, .sidebar, .ad, .advertisement, .cookie-banner, noscript'
  );
  elementsToRemove.forEach(el => el.remove());

  // Find main content area
  const mainSelectors = ['main', 'article', '[role="main"]', '.post-content', '.article-body', '.entry-content'];
  let mainContent = null;
  for (const selector of mainSelectors) {
    mainContent = clone.querySelector(selector);
    if (mainContent && mainContent.innerText.trim().length > 200) break;
    mainContent = null;
  }

  const textSource = mainContent ? mainContent.innerText : clone.innerText;
  let text = textSource.replace(/\s+/g, ' ').trim();

  // Extract headings structure
  const headings = [];
  document.querySelectorAll('h1, h2, h3').forEach(h => {
    headings.push({ level: parseInt(h.tagName[1]), text: h.textContent.trim().substring(0, 200) });
  });

  // Extract links for cross-referencing
  const links = [];
  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href');
    if (href && href.startsWith('http') && !href.includes(window.location.hostname)) {
      links.push({ url: href, text: a.textContent.trim().substring(0, 100) });
    }
  });

  // Limit content size
  const content = text.substring(0, 15000);

  return {
    title: ogTitle || title,
    url,
    description: ogDesc || metaDesc,
    keywords: metaKeywords,
    author: metaAuthor,
    publishedTime,
    content,
    headings: headings.slice(0, 20),
    externalLinks: links.slice(0, 15),
    structuredData,
    wordCount: text.split(/\s+/).length,
    detectedAt: new Date().toISOString(),
  };
}

/**
 * Detect if the current page is research-relevant and classify its type.
 * Returns a detection result with classification and confidence.
 */
function detectPageType() {
  const url = window.location.href.toLowerCase();
  const hostname = window.location.hostname.toLowerCase();
  const title = document.title.toLowerCase();
  const bodyText = document.body?.innerText?.substring(0, 2000)?.toLowerCase() || '';

  const signals = [];
  let researchScore = 0;

  // --- Signal: Academic/Research domains ---
  const academicDomains = [
    'scholar.google', 'arxiv.org', 'pubmed.ncbi', 'researchgate.net',
    'semanticscholar.org', 'ieee.org', 'acm.org', 'nature.com',
    'science.org', 'springer.com', 'wiley.com', 'biorxiv.org',
    'medrxiv.org', 'ssrn.com', 'jstor.org', 'ncbi.nlm.nih.gov',
  ];
  if (academicDomains.some(d => hostname.includes(d))) {
    signals.push('academic_domain');
    researchScore += 3;
  }

  // --- Signal: News domains ---
  const newsDomains = [
    'reuters.com', 'bbc.com', 'bbc.co.uk', 'nytimes.com', 'washingtonpost.com',
    'theguardian.com', 'economist.com', 'ft.com', 'bloomberg.com',
    'techcrunch.com', 'theverge.com', 'arstechnica.com', 'wired.com',
  ];
  if (newsDomains.some(d => hostname.includes(d))) {
    signals.push('news_domain');
    researchScore += 2;
  }

  // --- Signal: Technical/Documentation domains ---
  const techDomains = [
    'github.com', 'stackoverflow.com', 'docs.', 'developer.',
    'medium.com', 'dev.to', 'hackernoon.com', 'substack.com',
  ];
  if (techDomains.some(d => hostname.includes(d))) {
    signals.push('tech_domain');
    researchScore += 2;
  }

  // --- Signal: Page structure indicates article/research ---
  if (document.querySelector('article') || document.querySelector('[role="article"]')) {
    signals.push('article_element');
    researchScore += 1;
  }
  if (document.querySelector('meta[property="article:published_time"]')) {
    signals.push('article_meta');
    researchScore += 1;
  }
  if (document.querySelector('meta[name="citation_title"]')) {
    signals.push('citation_meta');
    researchScore += 2;
  }

  // --- Signal: Content length ---
  const wordCount = (document.body?.innerText || '').split(/\s+/).length;
  if (wordCount > 500) {
    signals.push('long_content');
    researchScore += 1;
  }
  if (wordCount > 2000) {
    signals.push('very_long_content');
    researchScore += 1;
  }

  // --- Signal: URL patterns ---
  const researchUrlPatterns = ['/research/', '/paper/', '/article/', '/study/', '/analysis/', '/report/', '/blog/'];
  if (researchUrlPatterns.some(p => url.includes(p))) {
    signals.push('research_url_pattern');
    researchScore += 1;
  }

  // Classify page type
  let pageType = 'general';
  let confidence = 0;

  if (researchScore >= 5) {
    if (signals.includes('academic_domain') || signals.includes('citation_meta')) {
      pageType = 'academic';
      confidence = 0.9;
    } else if (signals.includes('news_domain')) {
      pageType = 'news';
      confidence = 0.85;
    } else {
      pageType = 'research';
      confidence = 0.8;
    }
  } else if (researchScore >= 3) {
    pageType = 'article';
    confidence = 0.6;
  } else if (researchScore >= 1) {
    pageType = 'potentially_relevant';
    confidence = 0.3;
  }

  return {
    pageType,
    confidence,
    researchScore,
    signals,
    wordCount,
    isResearchRelevant: researchScore >= 3,
  };
}

/**
 * Generate auto-tags based on page content analysis.
 */
function generateAutoTags() {
  const title = document.title;
  const metaKeywords = document.querySelector('meta[name="keywords"]')?.content || '';
  const headings = Array.from(document.querySelectorAll('h1, h2'))
    .map(h => h.textContent.trim())
    .join(' ');

  const text = `${title} ${metaKeywords} ${headings}`.toLowerCase();
  const tags = [];

  // Topic detection via keyword matching
  const topicMap = {
    'ai-ml': ['machine learning', 'artificial intelligence', 'neural network', 'deep learning', 'llm', 'gpt', 'transformer'],
    'research': ['research', 'study', 'paper', 'analysis', 'methodology', 'findings'],
    'technology': ['software', 'technology', 'programming', 'api', 'cloud', 'devops'],
    'science': ['science', 'physics', 'chemistry', 'biology', 'experiment', 'hypothesis'],
    'business': ['business', 'market', 'startup', 'enterprise', 'revenue', 'growth'],
    'health': ['health', 'medical', 'clinical', 'patient', 'treatment', 'diagnosis'],
    'policy': ['policy', 'regulation', 'government', 'law', 'compliance'],
    'news': ['breaking', 'reported', 'announced', 'released', 'launched'],
  };

  for (const [tag, keywords] of Object.entries(topicMap)) {
    if (keywords.some(kw => text.includes(kw))) {
      tags.push(tag);
    }
  }

  // Add meta keywords as tags
  if (metaKeywords) {
    metaKeywords.split(',').slice(0, 5).forEach(kw => {
      const trimmed = kw.trim().toLowerCase().replace(/\s+/g, '-');
      if (trimmed.length > 2 && trimmed.length < 30) tags.push(trimmed);
    });
  }

  return [...new Set(tags)].slice(0, 10);
}

// --- Main execution ---
// Return content + detection for chrome.scripting.executeScript
const contentData = extractContent();
const detection = detectPageType();
const autoTags = generateAutoTags();

// Store page fingerprint for multi-page comparison
const pageFingerprint = {
  url: contentData.url,
  title: contentData.title,
  domain: window.location.hostname,
  pageType: detection.pageType,
  tags: autoTags,
  extractedAt: contentData.detectedAt,
};

({
  ...contentData,
  detection,
  autoTags,
  pageFingerprint,
});
