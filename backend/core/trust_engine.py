"""
Source Trust Engine.
Calculates multidimensional credibility scores for graph nodes (sources, documents).

Enhanced with URL pattern analysis, content quality heuristics, and expanded domain
database (Arch Issue #6).
"""
import re
import time
from urllib.parse import urlparse
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Known high-trust domains (expanded categories)
TRUSTED_DOMAINS = {
    # Academic / Scientific
    "nature.com": 0.95,
    "science.org": 0.95,
    "arxiv.org": 0.90,
    "ncbi.nlm.nih.gov": 0.95,
    "pubmed.ncbi.nlm.nih.gov": 0.95,
    "cell.com": 0.92,
    "springer.com": 0.88,
    "wiley.com": 0.87,
    "ieee.org": 0.90,
    "acm.org": 0.88,
    # Government / Institutional
    "who.int": 0.93,
    "cdc.gov": 0.93,
    "fda.gov": 0.90,
    "nist.gov": 0.92,
    "nih.gov": 0.93,
    # News / Media
    "reuters.com": 0.85,
    "apnews.com": 0.85,
    "bbc.com": 0.83,
    "bbc.co.uk": 0.83,
    "nytimes.com": 0.80,
    "washingtonpost.com": 0.78,
    "economist.com": 0.82,
    "ft.com": 0.82,
    # Tech / Developer
    "github.com": 0.80,
    "stackoverflow.com": 0.75,
    "docs.python.org": 0.85,
    "developer.mozilla.org": 0.85,
    "arxiv.org": 0.90,
    # Reference
    "wikipedia.org": 0.75,
    "britannica.com": 0.80,
    "merriam-webster.com": 0.78,
}

# Low-trust domain patterns
LOW_TRUST_PATTERNS = [
    r"\.blogspot\.",
    r"\.wordpress\.com$",
    r"\.wixsite\.com$",
    r"\.weebly\.com$",
    r"\.medium\.com$",
    r"\.substack\.com$",
]


class TrustEngine:
    """Evaluates source credibility using multi-dimensional trust scoring.
    
    Supports two modes (controlled by TRUST_ENGINE_MODE setting):
    - 'heuristic': Rule-based scoring using domain lists and URL patterns
    - 'ml': Enhanced scoring with content quality analysis
    """

    def __init__(self):
        self.mode = settings.TRUST_ENGINE_MODE

    def _analyze_url_pattern(self, url: str) -> dict:
        """Analyze URL structure for credibility signals."""
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        
        signals = {
            "is_https": parsed.scheme == "https",
            "subdomain_depth": len(parsed.netloc.split(".")) - 2,  # e.g. "a.b.example.com" = 2
            "path_depth": len([p for p in parsed.path.split("/") if p]),
            "has_query_params": bool(parsed.query),
            "is_short_url": len(url) < 80,
        }
        
        # Penalize deep subdomains (potential phishing/low-quality)
        if signals["subdomain_depth"] > 2:
            signals["subdomain_penalty"] = -0.15
        else:
            signals["subdomain_penalty"] = 0.0
        
        # Penalize low-trust hosting patterns
        for pattern in LOW_TRUST_PATTERNS:
            if re.search(pattern, domain):
                signals["hosting_penalty"] = -0.20
                break
        else:
            signals["hosting_penalty"] = 0.0
        
        return signals

    def _analyze_content_quality(self, content: str) -> dict:
        """Analyze content for quality heuristics."""
        if not content:
            return {"word_count": 0, "citation_density": 0.0, "has_dates": False, "quality_score": 0.3}
        
        words = content.split()
        word_count = len(words)
        
        # Count citations / references (approximate)
        citation_patterns = len(re.findall(r'\[\d+\]|\(\d{4}\)|https?://\S+', content))
        citation_density = min(1.0, citation_patterns / max(1, word_count / 100))
        
        # Check for date references (indicates recency)
        has_dates = bool(re.search(r'\b(20\d{2}|19\d{2})\b', content))
        
        # Quality score based on heuristics
        quality_score = 0.3  # baseline
        if word_count > 500:
            quality_score += 0.15
        if word_count > 2000:
            quality_score += 0.15
        if citation_density > 0.3:
            quality_score += 0.2
        if has_dates:
            quality_score += 0.1
        
        return {
            "word_count": word_count,
            "citation_density": round(citation_density, 3),
            "has_dates": has_dates,
            "quality_score": min(1.0, quality_score),
        }

    def evaluate_source(self, url: str, content: str = "", citations: int = 0) -> dict:
        """
        Evaluates a source URL and returns a comprehensive trust tensor.
        """
        domain = urlparse(url).netloc.replace("www.", "")
        
        # 1. Base Domain Trust
        trust_score = TRUSTED_DOMAINS.get(domain, 0.5)  # Default neutral trust
        if domain.endswith(".edu") or domain.endswith(".gov"):
            trust_score = max(trust_score, 0.85)
        
        # 2. URL Pattern Analysis (Arch Issue #6)
        url_signals = self._analyze_url_pattern(url)
        trust_score += url_signals.get("subdomain_penalty", 0.0)
        trust_score += url_signals.get("hosting_penalty", 0.0)
        if not url_signals["is_https"]:
            trust_score -= 0.1
        trust_score = max(0.0, min(1.0, trust_score))
            
        # 3. Content Quality Analysis (Arch Issue #6)
        content_analysis = self._analyze_content_quality(content)
        evidence_score = content_analysis["quality_score"]
            
        # 4. Citation Confidence
        citation_confidence = min(1.0, 0.5 + (citations * 0.1))
        
        # 5. Freshness Score
        freshness_score = 1.0 if content_analysis["has_dates"] else 0.7
        
        # 6. Bias Score
        bias_penalty = 0.0
        if "opinion" in url.lower() or "blog" in url.lower():
            bias_penalty = 0.3
        if "editorial" in url.lower():
            bias_penalty = max(bias_penalty, 0.25)
            
        # Composite calculation
        composite_score = (
            (trust_score * 0.35) +
            (evidence_score * 0.30) +
            (citation_confidence * 0.20) +
            (freshness_score * 0.15)
        ) - bias_penalty
        
        # Normalize 0.0 to 1.0
        composite_score = max(0.0, min(1.0, composite_score))
        
        logger.info("trust_engine_evaluated", url=url, composite_score=composite_score, mode=self.mode)
        
        return {
            "trust_score": round(trust_score, 3),
            "evidence_score": round(evidence_score, 3),
            "citation_confidence": round(citation_confidence, 3),
            "freshness_score": round(freshness_score, 3),
            "bias_penalty": round(bias_penalty, 3),
            "composite_score": round(composite_score, 3),
            "content_quality": content_analysis,
            "url_signals": url_signals,
            "evaluated_at": time.time(),
            "mode": self.mode,
        }
