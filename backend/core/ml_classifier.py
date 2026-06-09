"""
ML-based jailbreak and prompt injection classifier for CortexAI.

Supports two modes:
  1. **ML mode** (production): Loads a HuggingFace transformer model
     (default: deepset/deberta-v3-base-injection or configurable) for
     real classification with tokenization and inference.
  2. **Heuristic mode** (default/fallback): Multi-signal heuristic engine
     combining pattern matching, structural analysis, and entropy scoring.

Configuration:
    ML_CLASSIFIER_MODE: heuristic | ml
    ML_CLASSIFIER_MODEL: HuggingFace model name (default: deepset/deberta-v3-base-injection)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Optional

from backend.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Heuristic patterns — covers OWASP LLM Top 10 prompt injection vectors
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS: list[tuple[str, float, str]] = [
    # (pattern, weight, category)
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|guidelines)", 0.6, "instruction_override"),
    (r"disregard\s+(your|all|the)\s+(rules|instructions|training|guidelines)", 0.55, "instruction_override"),
    (r"you\s+are\s+now\s+(a|an|in)\s+", 0.4, "role_override"),
    (r"(system|developer)\s*prompt", 0.3, "system_probe"),
    (r"(dan|do\s+anything\s+now)\s*mode", 0.5, "jailbreak_named"),
    (r"print\s+(your|the)\s+(system|initial|hidden)\s+(prompt|instructions)", 0.5, "extraction"),
    (r"repeat\s+(your|the)\s+(system|initial)\s+(prompt|message)", 0.45, "extraction"),
    (r"bypass\s+(safety|content|moderation)\s*(filters?|restrictions?|rules?)", 0.55, "safety_bypass"),
    (r"act\s+as\s+if\s+you\s+(have\s+no|don'?t\s+have)\s+(restrictions?|rules?|limits?)", 0.5, "restriction_removal"),
    (r"pretend\s+(you\s+are|to\s+be)\s+(a\s+)?(hacker|attacker|unfiltered|unrestricted)", 0.5, "role_override"),
    (r"override\s+(your|the)\s+(safety|content)\s*(filter|guardrail|restriction)", 0.55, "safety_bypass"),
    (r"\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>|<\|im_start\|>", 0.7, "format_injection"),
    (r"new\s+instructions?\s*:", 0.35, "instruction_override"),
    (r"forget\s+(everything|all)\s+(you|that)\s+(know|learned|were\s+told)", 0.5, "instruction_override"),
    (r"jailbreak|jail\s*break", 0.4, "jailbreak_named"),
]

# Compiled regexes for performance
_COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), w, c) for p, w, c in _INJECTION_PATTERNS]


class MLClassifier:
    """
    Production-ready prompt injection classifier.

    In ML mode, loads a HuggingFace transformer for real classification.
    Falls back to multi-signal heuristics when ML model is unavailable.
    """

    def __init__(self):
        self._mode: str = "heuristic"
        self._ml_pipeline: Any = None  # HuggingFace pipeline
        self._ml_loaded: bool = False

    def initialize(self, mode: Optional[str] = None, model_name: Optional[str] = None) -> None:
        """Initialize the classifier. Call once at startup.

        Args:
            mode: "heuristic" or "ml". If None, reads from settings.
            model_name: HuggingFace model path. Defaults to deepset/deberta-v3-base-injection.
        """
        if mode is None:
            try:
                from backend.config import settings
                mode = getattr(settings, "ML_CLASSIFIER_MODE", "heuristic")
                model_name = getattr(settings, "ML_CLASSIFIER_MODEL", "deepset/deberta-v3-base-injection")
            except Exception:
                mode = "heuristic"

        self._mode = mode

        if self._mode == "ml":
            self._load_ml_model(model_name or "deepset/deberta-v3-base-injection")

    def _load_ml_model(self, model_name: str) -> None:
        """Attempt to load a HuggingFace text-classification pipeline."""
        try:
            from transformers import pipeline as hf_pipeline
            self._ml_pipeline = hf_pipeline(
                "text-classification",
                model=model_name,
                tokenizer=model_name,
                truncation=True,
                max_length=512,
                device=-1,  # CPU
            )
            self._ml_loaded = True
            self._mode = "ml"
            logger.info("ml_classifier_loaded", model=model_name)
        except ImportError:
            logger.warning(
                "transformers_not_installed",
                note="Install with: pip install transformers torch. Falling back to heuristic mode.",
            )
            self._mode = "heuristic"
        except Exception as e:
            logger.error("ml_classifier_load_error", model=model_name, error=str(e))
            self._mode = "heuristic"

    def classify(self, text: str) -> dict:
        """Classify if the text is a prompt injection or jailbreak attempt.

        Returns:
            dict with keys:
                - is_injection (bool)
                - confidence (float, 0-1)
                - reason (str)
                - mode (str): "ml" or "heuristic"
                - signals (list[str]): matched signal categories
        """
        if self._mode == "ml" and self._ml_pipeline:
            return self._classify_ml(text)
        return self._classify_heuristic(text)

    # ------------------------------------------------------------------
    # ML Classification
    # ------------------------------------------------------------------
    def _classify_ml(self, text: str) -> dict:
        """Classify using the loaded HuggingFace model."""
        try:
            result = self._ml_pipeline(text[:1024])[0]
            label = result.get("label", "")
            score = result.get("score", 0.5)

            # Most injection models use labels like "injection", "INJECTION", "LABEL_1"
            is_injection = label.upper() in ("INJECTION", "LABEL_1", "HARMFUL", "MALICIOUS")

            return {
                "is_injection": is_injection,
                "confidence": round(score, 4),
                "reason": f"ML model label={label}, score={score:.4f}",
                "mode": "ml",
                "signals": [label] if is_injection else [],
            }
        except Exception as e:
            logger.warning("ml_classify_error", error=str(e))
            # Fallback to heuristic on error
            return self._classify_heuristic(text)

    # ------------------------------------------------------------------
    # Heuristic Classification (multi-signal)
    # ------------------------------------------------------------------
    def _classify_heuristic(self, text: str) -> dict:
        """Multi-signal heuristic classification."""
        text_lower = text.lower()
        total_score = 0.0
        signals: list[str] = []

        # Signal 1: Pattern matching
        pattern_score, matched = self._score_patterns(text_lower)
        total_score += pattern_score
        signals.extend(matched)

        # Signal 2: Structural analysis (unusual formatting)
        struct_score = self._score_structure(text)
        total_score += struct_score
        if struct_score > 0:
            signals.append("structural_anomaly")

        # Signal 3: Entropy analysis (high entropy = obfuscation attempt)
        entropy_score = self._score_entropy(text)
        total_score += entropy_score
        if entropy_score > 0:
            signals.append("high_entropy_obfuscation")

        # Signal 4: Instruction density (too many imperative sentences)
        density_score = self._score_instruction_density(text)
        total_score += density_score
        if density_score > 0:
            signals.append("high_instruction_density")

        # Normalize score to 0-1
        confidence = min(total_score, 0.99)
        is_injection = confidence >= 0.5

        return {
            "is_injection": is_injection,
            "confidence": round(confidence, 4),
            "reason": f"Matched signals: {', '.join(signals)}" if signals else "No injection signals detected",
            "mode": "heuristic",
            "signals": signals,
        }

    def _score_patterns(self, text_lower: str) -> tuple[float, list[str]]:
        """Score based on regex pattern matches."""
        score = 0.0
        matched_categories: list[str] = []

        for compiled, weight, category in _COMPILED_PATTERNS:
            if compiled.search(text_lower):
                score += weight
                if category not in matched_categories:
                    matched_categories.append(category)

        return score, matched_categories

    @staticmethod
    def _score_structure(text: str) -> float:
        """Detect structural anomalies that suggest injection attempts."""
        score = 0.0

        # Excessive use of special delimiters
        special_delims = text.count("[") + text.count("{") + text.count("<")
        if special_delims > 10 and len(text) < 500:
            score += 0.15

        # Mixed case in suspicious patterns (e.g., "IgNoRe PrEvIoUs")
        if re.search(r"([a-z][A-Z]){4,}", text):
            score += 0.1

        # Base64 or hex-encoded content
        if re.search(r"[A-Za-z0-9+/]{40,}={0,2}", text):
            score += 0.2

        # Unicode homoglyphs (Cyrillic lookalikes)
        cyrillic_count = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
        if cyrillic_count > 3:
            score += 0.15

        return score

    @staticmethod
    def _score_entropy(text: str) -> float:
        """Detect abnormally high entropy suggesting obfuscation."""
        if len(text) < 20:
            return 0.0

        counter = Counter(text.lower())
        total = len(text)
        entropy = -sum((count / total) * math.log2(count / total) for count in counter.values())

        # Normal English text has entropy ~4.0-4.5
        # Obfuscated or encoded text has entropy > 5.5
        if entropy > 5.5:
            return 0.15
        return 0.0

    @staticmethod
    def _score_instruction_density(text: str) -> float:
        """Detect unusually high density of imperative instructions."""
        sentences = re.split(r"[.!?]+", text)
        if len(sentences) < 3:
            return 0.0

        imperative_starters = [
            "ignore", "disregard", "forget", "override", "bypass",
            "act as", "pretend", "repeat", "print", "show me",
            "you must", "you will", "do not follow", "don't follow",
        ]
        imperative_count = sum(
            1 for s in sentences
            if any(s.strip().lower().startswith(starter) for starter in imperative_starters)
        )

        ratio = imperative_count / len(sentences)
        if ratio > 0.5:
            return 0.15
        return 0.0


# Global singleton
ml_classifier = MLClassifier()
