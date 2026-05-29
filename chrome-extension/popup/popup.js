document.addEventListener('DOMContentLoaded', () => {
  const injectBtn = document.getElementById('inject-btn');
  const statusEl = document.getElementById('status');
  const sessionIdInput = document.getElementById('session-id');
  const tagsInput = document.getElementById('tags');
  const noteInput = document.getElementById('note');
  const optionsLink = document.getElementById('options-link');

  // Load saved session ID if any
  chrome.storage.local.get(['sessionId'], (res) => {
    if (res.sessionId && res.sessionId !== 'default') {
      sessionIdInput.value = res.sessionId;
    }
  });

  optionsLink.addEventListener('click', (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });

  injectBtn.addEventListener('click', async () => {
    injectBtn.disabled = true;
    statusEl.className = 'status loading';
    statusEl.textContent = 'Extracting page content...';

    try {
      // Get current active tab
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab) throw new Error("No active tab found.");

      // Execute content script to extract text
      const injectionResults = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js']
      });

      const extractedData = injectionResults[0].result;
      
      if (!extractedData) throw new Error("Failed to extract content.");

      statusEl.textContent = 'Sending to CortexAI...';

      // Parse tags
      const tags = tagsInput.value.split(',').map(t => t.trim()).filter(t => t);
      const sessionId = sessionIdInput.value.trim() || 'default';
      
      // Save session id preference
      if (sessionId !== 'default') {
        chrome.storage.local.set({ sessionId });
      }

      // Build payload
      const payload = {
        session_id: sessionId,
        url: extractedData.url,
        title: extractedData.title,
        content: extractedData.content,
        tags: tags,
        note: noteInput.value.trim()
      };

      // Send via background script to avoid CORS issues in popup
      chrome.runtime.sendMessage({ action: 'sendContext', payload }, (response) => {
        if (chrome.runtime.lastError) {
          throw new Error(chrome.runtime.lastError.message);
        }
        
        if (response && response.success) {
          statusEl.className = 'status success';
          statusEl.textContent = 'Successfully injected into CortexAI!';
          setTimeout(() => window.close(), 2000);
        } else {
          throw new Error(response?.error || "Unknown error occurred.");
        }
      });

    } catch (err) {
      statusEl.className = 'status error';
      statusEl.textContent = `Error: ${err.message}`;
      injectBtn.disabled = false;
    }
  });
});
