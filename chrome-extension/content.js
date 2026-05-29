// content.js - Extracts page content

function extractContent() {
  const title = document.title;
  const url = window.location.href;
  
  // Try to get meta description
  const metaDesc = document.querySelector('meta[name="description"]')?.content || '';
  
  // Very basic readability extraction (strip scripts, styles, nav)
  const clone = document.body.cloneNode(true);
  const elementsToRemove = clone.querySelectorAll('script, style, nav, header, footer, iframe, img, svg');
  elementsToRemove.forEach(el => el.remove());
  
  // Collapse whitespace
  let text = clone.innerText;
  text = text.replace(/\s+/g, ' ').trim();
  
  // Limit to reasonable size for context injection (~10k chars)
  const content = text.substring(0, 10000);
  
  return {
    title,
    url,
    description: metaDesc,
    content
  };
}

// Return directly for chrome.scripting.executeScript
extractContent();
