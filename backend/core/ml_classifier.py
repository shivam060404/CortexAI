"""
ML-based jailbreak classifier for CortexAI.
Provides a lightweight heuristic and mock ML classifier to detect harmful prompts.
"""

from backend.core.logger import get_logger

logger = get_logger(__name__)

class MLClassifier:
    """
    In a real production environment, this would load a HuggingFace model 
    (e.g., deepset/deberta-v3-base-injection) to classify prompt injections.
    For this implementation, it uses advanced heuristics to act as the classifier.
    """
    
    def __init__(self):
        self.injection_patterns = [
            "ignore previous instructions",
            "system prompt",
            "you are now",
            "developer mode",
            "dan mode",
            "print your instructions",
            "bypass",
            "override"
        ]

    def classify(self, text: str) -> dict:
        """
        Classifies if the text is a prompt injection or jailbreak attempt.
        Returns:
            dict: {"is_injection": bool, "confidence": float, "reason": str}
        """
        text_lower = text.lower()
        score = 0.0
        matched_patterns = []

        for pattern in self.injection_patterns:
            if pattern in text_lower:
                score += 0.4
                matched_patterns.append(pattern)
        
        # Simple heuristic threshold
        if score > 0.7:
            return {
                "is_injection": True, 
                "confidence": min(score, 0.99), 
                "reason": f"Matched patterns: {', '.join(matched_patterns)}"
            }
            
        return {
            "is_injection": False,
            "confidence": 1.0 - score,
            "reason": ""
        }

# Global singleton
ml_classifier = MLClassifier()
