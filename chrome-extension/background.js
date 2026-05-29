// background.js - Service Worker

chrome.runtime.onInstalled.addListener(() => {
  // Set default settings on install
  chrome.storage.local.get(['serverUrl', 'sessionId'], (result) => {
    if (!result.serverUrl) {
      chrome.storage.local.set({ serverUrl: 'http://localhost:8000' });
    }
    if (!result.sessionId) {
      chrome.storage.local.set({ sessionId: 'default' });
    }
  });
});

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'sendContext') {
    sendContextToCortex(request.payload)
      .then(res => sendResponse({ success: true, data: res }))
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true; // Keep message channel open for async response
  }
});

async function sendContextToCortex(payload) {
  const { serverUrl } = await chrome.storage.local.get('serverUrl');
  
  if (!serverUrl) throw new Error("CortexAI Server URL not configured.");
  
  const url = `${serverUrl.replace(/\/$/, '')}/api/context/pages`;
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload)
  });
  
  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`Failed to send context: ${response.status} - ${errText}`);
  }
  
  return await response.json();
}
