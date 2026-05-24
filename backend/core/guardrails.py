"""
Intelligence Guardrails Layer — 3-Layer Jailbreak Defense System.

Layer 1 (INPUT):  scan_user_input()      — blocks malicious user queries BEFORE the LLM sees them
Layer 2 (TOOLS):  scan_for_prompt_injection() — sanitizes poisoned tool/web content mid-loop
Layer 3 (OUTPUT): scan_llm_output()      — blocks harmful LLM responses BEFORE they reach the user

Also provides: PII redaction, citation verification, and scope drift detection.
"""
import re
from typing import Set, Tuple
from dataclasses import dataclass
from backend.core.logger import get_logger
from backend.config import settings
import importlib.util

logger = get_logger(__name__)

_encoder = None
def get_encoder():
    global _encoder
    if _encoder is None and importlib.util.find_spec("semantic_router"):
        from semantic_router.encoders import HuggingFaceEncoder
        _encoder = HuggingFaceEncoder()
    return _encoder


# ═══════════════════════════════════════════════════════════════════════
# PATTERN DATABASES
# ═══════════════════════════════════════════════════════════════════════

# Comprehensive prompt injection / jailbreak patterns (covers OWASP Top 10 LLM risks)
PROMPT_INJECTION_PATTERNS = [
    # Direct instruction override
    r"(?i)\bignore\s*(all\s*)?previous\s*instructions\b",
    r"(?i)\bforget\s*(all\s*)?(previous|prior|above)\b",
    r"(?i)\bignore\s*(the\s*)?(above|system)\s*(instructions|prompt|rules)\b",
    r"(?i)\bdisregard\s*(all\s*)?(previous|prior|above|system)\b",
    r"(?i)\boverride\s*(all\s*)?(previous|system|safety)\b",
    # Role hijacking
    r"(?i)\byou\s*are\s*now\b",
    r"(?i)\bact\s*as\s*(if\s*you\s*are|a)\b",
    r"(?i)\bpretend\s*(you\s*are|to\s*be)\b",
    r"(?i)\broleplay\s*as\b",
    r"(?i)\bswitch\s*to\s*(\w+\s*)?mode\b",
    # DAN and known jailbreaks
    r"(?i)\bdo\s*anything\s*now\b",
    r"(?i)\bjailbreak\b",
    r"(?i)\bdeveloper\s*mode\b",
    r"(?i)\bno\s*restrictions\s*mode\b",
    r"(?i)\bunlocked\s*mode\b",
    r"(?i)\bevil\s*(confident\s*)?mode\b",
    # System prompt extraction
    r"(?i)\bnew\s*system\s*prompt\b",
    r"(?i)\b(show|print|reveal|repeat|output)\s*(me\s*)?(your|the)\s*(system\s*)?(prompt|instructions|rules)\b",
    r"(?i)\bwhat\s*(are|is)\s*your\s*(system\s*)?(prompt|instructions|rules)\b",
    # Encoding/obfuscation attacks
    r"(?i)\bencode\s*(this|the)\s*(in|as|to)\s*(base64|hex|rot13)\b",
    r"(?i)\btranslate\s*to\s*(pig\s*latin|morse|binary)\b",
    # Delimiter injection
    r"(?i)<\|?(system|user|assistant|im_start|im_end)\|?>",
    r"(?i)\[INST\]",
    r"(?i)\[\/INST\]",
    r"(?i)<<SYS>>",
]

# Harmful content categories for output scanning
HARMFUL_OUTPUT_PATTERNS = [
    # Weapons / violence
    r"(?i)\b(how\s*to\s*(make|build|create|construct)\s*(a\s*)?(bomb|explosive|weapon|gun|firearm))\b",
    r"(?i)\b(instructions\s*for\s*(making|building|creating)\s*(a\s*)?(bomb|explosive|weapon))\b",
    # Illegal activities
    r"(?i)\b(how\s*to\s*(hack|crack|break\s*into)\s*(a\s*)?(server|system|account|password))\b",
    r"(?i)\b(step.by.step\s*(guide|instructions)\s*(to|for)\s*(hack|exploit|bypass))\b",
    # Self-harm
    r"(?i)\b(how\s*to\s*(commit|attempt)\s*suicide)\b",
    r"(?i)\b(methods\s*(of|for)\s*(self.harm|suicide))\b",
    # Drug manufacturing
    r"(?i)\b(how\s*to\s*(make|synthesize|cook|manufacture)\s*(meth|cocaine|heroin|fentanyl|drugs))\b",
]

# PII patterns
PII_PATTERNS = {
    "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "PHONE": r"\b(?:\+?(\d{1,3}))?[-. (]*(\d{3})[-. )]*(\d{3})[-. ]*(\d{4})(?: *x(\d+))?\b",
    "SSN": r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b",
    "CREDIT_CARD": r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|6(?:011|5[0-9][0-9])[0-9]{12}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|(?:2131|1800|35\d{3})\d{11})\b"
}


# ═══════════════════════════════════════════════════════════════════════
# RESPONSE OBJECTS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class InputScanResult:
    """Result of scanning user input for jailbreak attempts."""
    is_safe: bool
    sanitized_query: str
    blocked_patterns: list[str]
    risk_score: float  # 0.0 (safe) to 1.0 (definitely malicious)
    
    @property
    def rejection_message(self) -> str:
        if self.is_safe:
            return ""
        return (
            "⚠️ Your query was flagged by our safety system. "
            "CortexAI is designed exclusively for legitimate research purposes. "
            "Please rephrase your query to focus on a valid research topic."
        )


@dataclass
class OutputScanResult:
    """Result of scanning LLM output for harmful content."""
    is_safe: bool
    sanitized_content: str
    blocked_categories: list[str]


# ═══════════════════════════════════════════════════════════════════════
# LAYER 1: USER INPUT GUARD (runs at WebSocket entry point)
# ═══════════════════════════════════════════════════════════════════════

def scan_user_input(query: str) -> InputScanResult:
    """
    Layer 1: Scans the raw user query BEFORE it enters the LangGraph agent.
    
    Returns InputScanResult with:
    - is_safe: True if the query is clean
    - sanitized_query: cleaned version (injection patterns stripped)
    - blocked_patterns: list of matched jailbreak patterns
    - risk_score: 0.0 to 1.0
    """
    if not query or not settings.GUARD_ENABLE_INJECTION_SHIELD:
        return InputScanResult(is_safe=True, sanitized_query=query, blocked_patterns=[], risk_score=0.0)
    
    blocked = []
    sanitized = query
    
    for pattern in PROMPT_INJECTION_PATTERNS:
        matches = re.findall(pattern, query)
        if matches:
            blocked.append(pattern)
            sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)
    
    # Calculate risk score based on number of patterns matched
    risk_score = min(1.0, len(blocked) * 0.35)
    
    # High risk: 2+ patterns matched = hard block
    # Medium risk: 1 pattern matched = allow with sanitization
    is_safe = risk_score < 0.6  # blocks at 2+ pattern matches
    
    if blocked:
        logger.warning(
            "user_input_injection_detected",
            patterns_matched=len(blocked),
            risk_score=risk_score,
            is_blocked=not is_safe,
            query_preview=query[:80],
        )
    
    # Clean up extra whitespace from sanitization
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    return InputScanResult(
        is_safe=is_safe,
        sanitized_query=sanitized if is_safe else "",
        blocked_patterns=blocked,
        risk_score=risk_score,
    )


# ═══════════════════════════════════════════════════════════════════════
# LAYER 2: TOOL OUTPUT GUARD (runs inside guarded_tool_node)
# ═══════════════════════════════════════════════════════════════════════

def scan_for_prompt_injection(content: str) -> str:
    """Layer 2: Detects and neutralizes adversarial prompt injection patterns in tool results."""
    if not settings.GUARD_ENABLE_INJECTION_SHIELD or not content:
        return content

    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, content):
            logger.warning("prompt_injection_in_tool_output", pattern_match=pattern)
            content = re.sub(pattern, "[MALICIOUS_PROMPT_BLOCKED]", content, flags=re.IGNORECASE)

    return content


# ═══════════════════════════════════════════════════════════════════════
# LAYER 3: LLM OUTPUT GUARD (runs before response reaches user)
# ═══════════════════════════════════════════════════════════════════════

def scan_llm_output(content: str) -> OutputScanResult:
    """
    Layer 3: Scans LLM-generated text BEFORE it is streamed to the user via WebSocket.
    
    Checks for harmful content categories (weapons, illegal, self-harm, drugs).
    Returns OutputScanResult with safety status and sanitized content.
    """
    if not content or not settings.GUARD_ENABLE_OUTPUT_MODERATION:
        return OutputScanResult(is_safe=True, sanitized_content=content, blocked_categories=[])
    
    blocked_categories = []
    sanitized = content
    
    for pattern in HARMFUL_OUTPUT_PATTERNS:
        if re.search(pattern, content):
            # Extract a human-readable category name from the pattern
            category = _extract_category(pattern)
            blocked_categories.append(category)
            sanitized = re.sub(
                pattern,
                "[CONTENT BLOCKED: This information cannot be provided for safety reasons]",
                sanitized,
                flags=re.IGNORECASE
            )
    
    is_safe = len(blocked_categories) == 0
    
    if not is_safe:
        logger.warning(
            "harmful_llm_output_blocked",
            categories=blocked_categories,
            content_preview=content[:100],
        )
    
    return OutputScanResult(
        is_safe=is_safe,
        sanitized_content=sanitized,
        blocked_categories=blocked_categories,
    )


def _extract_category(pattern: str) -> str:
    """Extract a human-readable category from a regex pattern."""
    if "bomb" in pattern or "weapon" in pattern or "explosive" in pattern:
        return "weapons_violence"
    elif "hack" in pattern or "exploit" in pattern or "bypass" in pattern:
        return "illegal_hacking"
    elif "suicide" in pattern or "self.harm" in pattern:
        return "self_harm"
    elif "meth" in pattern or "cocaine" in pattern or "drug" in pattern:
        return "drug_manufacturing"
    return "unknown_harmful"


# ═══════════════════════════════════════════════════════════════════════
# PII REDACTION
# ═══════════════════════════════════════════════════════════════════════

def redact_pii(content: str) -> str:
    """Masks PII like emails, phone numbers, and SSNs from incoming text."""
    if not settings.GUARD_ENABLE_PII_REDACTION or not content:
        return content

    for pii_type, pattern in PII_PATTERNS.items():
        if re.search(pattern, content):
            logger.warning("pii_detected_and_redacted", type=pii_type)
            content = re.sub(pattern, f"[REDACTED_{pii_type}]", content)

    return content


# ═══════════════════════════════════════════════════════════════════════
# CITATION VERIFICATION
# ═══════════════════════════════════════════════════════════════════════

def verify_citations(report_markdown: str, accessed_urls: Set[str]) -> Tuple[str, list[str]]:
    """Check markdown format links `[text](url)` against actual accessed URLs.
    
    Returns:
        A tuple of (modified_report_markdown, list_of_fabricated_urls)
    """
    if not accessed_urls:
        return report_markdown, []

    fabricated = []
    
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    
    def replacer(match):
        text = match.group(1)
        url = match.group(2)
        
        is_verified = False
        for a_url in accessed_urls:
            if url in a_url or a_url in url:
                is_verified = True
                break
                
        if not is_verified and url.startswith("http"):
            fabricated.append(url)
            return f"[{text}]({url} ⚠️ Unverified)"
        return match.group(0)

    modified_report = re.sub(link_pattern, replacer, report_markdown)
    
    if fabricated:
        logger.warning("fabricated_citations_detected", count=len(fabricated), urls=fabricated)
        
    return modified_report, fabricated


# ═══════════════════════════════════════════════════════════════════════
# SCOPE DRIFT DETECTION
# ═══════════════════════════════════════════════════════════════════════

def check_scope_drift(query: str, recent_actions: list[str]) -> bool:
    """Semantic Router based scope drift detection."""
    if not recent_actions or len(recent_actions) < 3:
        return False
        
    try:
        from semantic_router import Route, RouteLayer
        encoder = get_encoder()
        if not encoder:
            return False
            
        target_route = Route(
            name="core_topic",
            utterances=[query, f"{query} research", f"information about {query}"]
        )
        
        layer = RouteLayer(encoder=encoder, routes=[target_route])
        
        # Check the most recent actions
        action_text = " ".join(recent_actions[-3:])
        route_choice = layer(action_text)
        
        # If the recent actions don't map back to the core topic route, it's drifting
        if not route_choice or route_choice.name != "core_topic":
            logger.warning("semantic_scope_drift_detected", query=query[:50])
            return True
            
        return False
    except Exception as e:
        logger.error("semantic_router_error", error=str(e))
        return False
