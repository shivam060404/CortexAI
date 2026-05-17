import re
from urllib.parse import urlparse
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Heuristic domain credibility tiers (Base: 50)
HIGH_CREDIBILITY_DOMAINS = {
    "edu": 30, "gov": 30, "org": 10,
    "nature.com": 40, "science.org": 40, "cell.com": 40, "thelancet.com": 40,
    "ncbi.nlm.nih.gov": 40, "pubmed.ncbi.nlm.nih.gov": 40, "arxiv.org": 35,
    "ieee.org": 35, "acm.org": 35, "mit.edu": 35, "harvard.edu": 35,
    "stanford.edu": 35, "ox.ac.uk": 35, "cam.ac.uk": 35, "wikipedia.org": 20,
    "reuters.com": 20, "apnews.com": 20, "bbc.com": 20, "bbc.co.uk": 20,
    "npr.org": 20, "wsj.com": 15, "nytimes.com": 15, "bloomberg.com": 15,
}

LOW_CREDIBILITY_DOMAINS = {
    "quora.com": -20, "reddit.com": -10, "medium.com": -10, "yahoo.com": -15,
    "facebook.com": -25, "twitter.com": -15, "x.com": -15, "tiktok.com": -30,
    "pinterest.com": -30, "buzzfeed.com": -25, "huffpost.com": -15,
}

def calculate_credibility_score(url: str, content: str = "") -> int:
    """Calculate a 0-100 credibility score for a source based on its domain and content."""
    score = 50  # Baseline score

    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname.lower() if parsed_url.hostname else ""
        if hostname.startswith("www."):
            hostname = hostname[4:]
        
        # 1. Domain Heuristics
        # Check exact match first
        if hostname in HIGH_CREDIBILITY_DOMAINS:
            score += HIGH_CREDIBILITY_DOMAINS[hostname]
        elif hostname in LOW_CREDIBILITY_DOMAINS:
            score += LOW_CREDIBILITY_DOMAINS[hostname]
        else:
            # Check TLDs
            tld = hostname.split('.')[-1]
            if tld in HIGH_CREDIBILITY_DOMAINS:
                score += HIGH_CREDIBILITY_DOMAINS[tld]
            elif tld in LOW_CREDIBILITY_DOMAINS:
                score += LOW_CREDIBILITY_DOMAINS[tld]

        # 2. Path Heuristics (Academic/PDFs)
        path = parsed_url.path.lower()
        if path.endswith(".pdf"):
            score += 10
        if "/article/" in path or "/paper/" in path or "/research/" in path:
            score += 10

        # 3. Content Heuristics (Citations/References proxies)
        if content:
            content_lower = content.lower()
            # Look for academic markers
            if "abstract" in content_lower and "conclusion" in content_lower:
                score += 5
            if "doi:" in content_lower or "doi.org" in content_lower:
                score += 10
            
            # Simple citation density proxy: count [1], [2], (Author, Year) patterns
            citation_matches = len(re.findall(r'\[\d+\]|\(\w+ et al\., \d{4}\)|\(\w+, \d{4}\)', content))
            if citation_matches > 0:
                score += min(15, citation_matches * 3)  # Up to 15 bonus points for citations
            
    except Exception as e:
        logger.warning("credibility_scoring_failed", url=url, error=str(e))
    
    # Bound between 0 and 100
    return max(0, min(100, score))


def calculate_semantic_score(query: str, content: str) -> int:
    """Lightweight extraction proxy for semantic similarity.
    Scores 0-100 based on the density of query keywords in the content."""
    if not query or not content:
        return 0
    
    # Remove filler words and lowercase
    fillers = {"the", "a", "an", "is", "are", "and", "or", "in", "on", "of", "to", "for", "with"}
    query_words = set([w.lower() for w in re.split(r'\W+', query) if w and w.lower() not in fillers])
    if not query_words:
        return 50  # fallback
    
    content_lower = content.lower()
    matches = sum(1 for word in query_words if word in content_lower)
    
    # Calculate density (matches / expected keyword count)
    density = matches / len(query_words)
    score = int(density * 100)
    
    # Bonus if the exact phrase exists
    if len(query.split()) > 1 and query.lower() in content_lower:
        score += 20
        
    return min(100, score)


def rank_search_results(query: str, results: list) -> list:
    """
    Takes raw search results, calculates credibility AND semantic scores,
    sorts them descending, and formats them for the LLM.
    """
    if not results or not isinstance(results, list):
        return results

    ranked_results = []
    for res in results:
        if not isinstance(res, dict):
            res = {"content": str(res), "url": "unknown"}
            
        url = res.get("url", "unknown")
        content = res.get("content", "")
        relevance = res.get("score", 0.5) 
        
        # Calculate Credibility (Domain + Path + Citations)
        cred = calculate_credibility_score(url, content)
        
        # Calculate Semantic Score (Keyword overlap context)
        semantic = calculate_semantic_score(query, content)
        
        # Combined score: 40% Credibility, 40% Semantic, 20% Search Engine Relevance
        combined_score = (cred * 0.4) + (semantic * 0.4) + (relevance * 100 * 0.2)
        
        res_copy = res.copy()
        res_copy["credibility_score"] = cred
        res_copy["semantic_score"] = semantic
        res_copy["combined_score"] = combined_score
        
        # Format explicitly for LLM
        res_copy["formatted_content"] = f"[Rank Score: {int(combined_score)}/100 | Credibility: {cred}/100]\n{content}"
        
        ranked_results.append(res_copy)

    # Sort descending by combined score
    ranked_results.sort(key=lambda x: x["combined_score"], reverse=True)
    
    return ranked_results
