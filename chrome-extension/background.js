// =============================================================================
// background.js — Service Worker with Auto-Detection & Multi-Page Compare
// =============================================================================

// --- Storage keys ---
const STORED_PAGES_KEY = 'cortexai_collected_pages';
const AUTO_DETECT_KEY = 'cortexai_auto_detect';
const MAX_STORED_PAGES = 50;

// --- Install handler ---
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['serverUrl', 'sessionId', AUTO_DETECT_KEY], (result) => {
    if (!result.serverUrl) {
      chrome.storage.local.set({ serverUrl: 'http://localhost:8000' });
    }
    if (!result.sessionId) {
      chrome.storage.local.set({ sessionId: 'default' });
    }
    if (result[AUTO_DETECT_KEY] === undefined) {
      chrome.storage.local.set({ [AUTO_DETECT_KEY]: true });
    }
  });
});

// --- Message listener ---
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  switch (request.action) {
    case 'sendContext':
      sendContextToCortex(request.payload)
        .then(res => sendResponse({ success: true, data: res }))
        .catch(err => sendResponse({ success: false, error: err.message }));
      return true;

    case 'autoDetect':
      autoDetectPage(sender.tab)
        .then(res => sendResponse({ success: true, data: res }))
        .catch(err => sendResponse({ success: false, error: err.message }));
      return true;

    case 'collectForCompare':
      collectPageForCompare(sender.tab)
        .then(res => sendResponse({ success: true, data: res }))
        .catch(err => sendResponse({ success: false, error: err.message }));
      return true;

    case 'getCollectedPages':
      chrome.storage.local.get([STORED_PAGES_KEY], (result) => {
        sendResponse({ success: true, pages: result[STORED_PAGES_KEY] || [] });
      });
      return true;

    case 'clearCollectedPages':
      chrome.storage.local.set({ [STORED_PAGES_KEY]: [] })
        .then(() => sendResponse({ success: true }))
        .catch(err => sendResponse({ success: false, error: err.message }));
      return true;

    case 'comparePages':
      comparePages(request.pageUrls)
        .then(res => sendResponse({ success: true, data: res }))
        .catch(err => sendResponse({ success: false, error: err.message }));
      return true;
  }
});

// --- Tab change listener for auto-detection ---
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete' || !tab.url) return;
  if (tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) return;

  // Check if auto-detection is enabled
  chrome.storage.local.get([AUTO_DETECT_KEY], async (result) => {
    if (!result[AUTO_DETECT_KEY]) return;

    try {
      const detection = await autoDetectPage(tab);
      if (detection && detection.isResearchRelevant) {
        // Show badge indicator for research-relevant pages
        chrome.action.setBadgeText({ tabId, text: '●' });
        chrome.action.setBadgeBackgroundColor({ tabId, color: '#4CAF50' });
      }
    } catch (e) {
      // Silent fail for auto-detection
    }
  });
});

// =============================================================================
// Core Functions
// =============================================================================

/**
 * Run auto-detection on a tab: extract content, detect page type.
 */
async function autoDetectPage(tab) {
  if (!tab?.id) return null;

  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ['content.js'],
  });

  const data = results?.[0]?.result;
  if (!data) return null;

  return {
    url: data.url,
    title: data.title,
    detection: data.detection,
    autoTags: data.autoTags,
    isResearchRelevant: data.detection?.isResearchRelevant || false,
  };
}

/**
 * Collect a page's content for multi-page comparison.
 */
async function collectPageForCompare(tab) {
  if (!tab?.id) throw new Error('No active tab');

  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ['content.js'],
  });

  const data = results?.[0]?.result;
  if (!data) throw new Error('Failed to extract page content');

  // Store in local storage
  const { [STORED_PAGES_KEY]: existingPages = [] } = await chrome.storage.local.get([STORED_PAGES_KEY]);

  // Deduplicate by URL
  const filtered = existingPages.filter(p => p.url !== data.url);
  const pageEntry = {
    url: data.url,
    title: data.title,
    description: data.description,
    content: data.content,
    headings: data.headings,
    autoTags: data.autoTags,
    pageType: data.detection?.pageType || 'general',
    wordCount: data.wordCount,
    collectedAt: new Date().toISOString(),
  };

  const updatedPages = [pageEntry, ...filtered].slice(0, MAX_STORED_PAGES);
  await chrome.storage.local.set({ [STORED_PAGES_KEY]: updatedPages });

  // Send to CortexAI backend
  try {
    await sendContextToCortex({
      pages: [pageEntry],
      action: 'collect',
      tags: data.autoTags,
    });
  } catch (e) {
    // Non-fatal: page stored locally even if backend fails
  }

  return { collected: true, totalPages: updatedPages.length, page: pageEntry };
}

/**
 * Compare collected pages and generate a comparison report.
 */
async function comparePages(pageUrls) {
  const { [STORED_PAGES_KEY]: storedPages = [] } = await chrome.storage.local.get([STORED_PAGES_KEY]);

  const pagesToCompare = pageUrls
    ? storedPages.filter(p => pageUrls.includes(p.url))
    : storedPages.slice(0, 5);

  if (pagesToCompare.length < 2) {
    return { error: 'Need at least 2 pages to compare', pages: pagesToCompare.length };
  }

  // Generate comparison data
  const comparison = {
    pages: pagesToCompare.map(p => ({
      url: p.url,
      title: p.title,
      domain: new URL(p.url).hostname,
      wordCount: p.wordCount,
      pageType: p.pageType,
      tags: p.autoTags,
      headings: p.headings?.slice(0, 5) || [],
    })),
    commonTags: findCommonTags(pagesToCompare),
    summary: generateComparisonSummary(pagesToCompare),
    generatedAt: new Date().toISOString(),
  };

  // Send comparison to CortexAI backend
  try {
    const result = await sendContextToCortex({
      pages: pagesToCompare,
      action: 'compare',
      comparison,
    });
    comparison.backendResult = result;
  } catch (e) {
    // Return local comparison even if backend fails
  }

  return comparison;
}

// =============================================================================
// Helpers
// =============================================================================

/**
 * Send context data to the CortexAI backend.
 */
async function sendContextToCortex(payload) {
  const { serverUrl } = await chrome.storage.local.get('serverUrl');
  if (!serverUrl) throw new Error('CortexAI Server URL not configured.');

  const url = `${serverUrl.replace(/\/$/, '')}/api/context/pages`;

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`Failed to send context: ${response.status} - ${errText}`);
  }

  return await response.json();
}

/**
 * Find tags common across multiple pages.
 */
function findCommonTags(pages) {
  if (pages.length < 2) return [];
  const tagCounts = {};
  pages.forEach(p => {
    (p.autoTags || []).forEach(tag => {
      tagCounts[tag] = (tagCounts[tag] || 0) + 1;
    });
  });
  return Object.entries(tagCounts)
    .filter(([_, count]) => count >= 2)
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count);
}

/**
 * Generate a text summary comparing pages.
 */
function generateComparisonSummary(pages) {
  const domains = [...new Set(pages.map(p => new URL(p.url).hostname))];
  const totalWords = pages.reduce((sum, p) => sum + (p.wordCount || 0), 0);
  const avgWords = Math.round(totalWords / pages.length);
  const types = [...new Set(pages.map(p => p.pageType))];

  return {
    pageCount: pages.length,
    uniqueDomains: domains.length,
    domains,
    totalWordCount: totalWords,
    averageWordCount: avgWords,
    pageTypes: types,
    longest: pages.reduce((a, b) => (a.wordCount || 0) > (b.wordCount || 0) ? a : b).title,
    shortest: pages.reduce((a, b) => (a.wordCount || 0) < (b.wordCount || 0) ? a : b).title,
  };
}
