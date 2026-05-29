"""
Source Trust Engine.
Calculates multidimensional credibility scores for graph nodes (sources, documents).
"""
import time
from urllib.parse import urlparse
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Known high-trust domains (could be loaded from DB)
TRUSTED_DOMAINS = {
    "nature.com": 0.95,
    "science.org": 0.95,
    "arxiv.org": 0.90,
    "ncbi.nlm.nih.gov": 0.95,
    "reuters.com": 0.85,
    "apnews.com": 0.85,
    "github.com": 0.80,
    "wikipedia.org": 0.75,
}

class TrustEngine:
    def __init__(self):
        pass

    def evaluate_source(self, url: str, content: str = "", citations: int = 0) -> dict:
        """
        Evaluates a source URL and returns a comprehensive trust tensor.
        """
        domain = urlparse(url).netloc.replace("www.", "")
        
        # 1. Base Domain Trust
        trust_score = TRUSTED_DOMAINS.get(domain, 0.5)  # Default neutral trust
        if domain.endswith(".edu") or domain.endswith(".gov"):
            trust_score = max(trust_score, 0.85)
            
        # 2. Evidence Score (Proxy: length and density of claims, simulated here)
        # Real implementation would use NLP to count factual claims vs opinions
        evidence_score = 0.5
        if len(content) > 2000:
            evidence_score += 0.2
            
        # 3. Citation Confidence
        # How many other nodes in the Context Graph point to this?
        citation_confidence = min(1.0, 0.5 + (citations * 0.1))
        
        # 4. Freshness Score
        # For this prototype, assume fresh unless marked otherwise
        freshness_score = 1.0
        
        # 5. Bias Score (Lower is better, inverted for overall calculation)
        # Real implementation: Sentiment analysis variance. Simulated:
        bias_penalty = 0.0
        if "opinion" in url.lower() or "blog" in url.lower():
            bias_penalty = 0.3
            
        # Composite calculation
        composite_score = (
            (trust_score * 0.4) +
            (evidence_score * 0.3) +
            (citation_confidence * 0.2) +
            (freshness_score * 0.1)
        ) - bias_penalty
        
        # Normalize 0.0 to 1.0
        composite_score = max(0.0, min(1.0, composite_score))
        
        logger.info("trust_engine_evaluated", url=url, composite_score=composite_score)
        
        return {
            "trust_score": trust_score,
            "evidence_score": evidence_score,
            "citation_confidence": citation_confidence,
            "freshness_score": freshness_score,
            "bias_penalty": bias_penalty,
            "composite_score": composite_score,
            "evaluated_at": time.time()
        }
