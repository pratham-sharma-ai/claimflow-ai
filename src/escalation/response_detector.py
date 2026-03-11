"""
Response Detector for ClaimFlow AI.

Analyzes insurer responses to detect templated/repeated replies
and determine if substantive progress has been made.
"""

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from ..llm.gemini_client import GeminiClient
from ..utils.logger import get_logger

logger = get_logger("claimflow.detector")


@dataclass
class ResponseAnalysis:
    """Analysis result for an insurer response."""
    is_templated: bool
    similarity_to_previous: float
    new_points_addressed: list[str]
    recommendation: str  # "auto_escalate", "manual_review", "positive_progress"
    key_phrases_detected: list[str]
    escalation_blocked: bool
    explanation: str


class ResponseDetector:
    """
    Detects templated responses and tracks escalation progress.

    Uses both heuristic matching and LLM analysis to determine
    if insurer responses are substantive or automated.
    """

    # Common templated phrases that indicate non-substantive response
    TEMPLATE_PHRASES = [
        "we regret to inform",
        "as per our records",
        "your claim has been reviewed",
        "after careful consideration",
        "we are unable to process",
        "as mentioned in our previous",
        "we appreciate your patience",
        "our decision remains unchanged",
        "please refer to the policy terms",
        "the claim stands rejected",
        "we have already communicated",
        "no further action can be taken",
    ]

    # Phrases that indicate positive progress
    PROGRESS_PHRASES = [
        "we are reviewing your case",
        "escalated to senior",
        "medical board will review",
        "compliance team",
        "additional information has been noted",
        "we will revert within",
        "your case is being reconsidered",
    ]

    def __init__(
        self,
        llm_client: GeminiClient | None = None,
        similarity_threshold: float = 0.85,
    ):
        """
        Initialize response detector.

        Args:
            llm_client: Optional Gemini client for advanced analysis.
            similarity_threshold: Threshold for detecting similar responses (0-1).
        """
        self.llm_client = llm_client
        self.similarity_threshold = similarity_threshold
        self._response_history: list[str] = []

    def analyze(
        self,
        response_text: str,
        previous_responses: list[str] | None = None,
        case_context: str | None = None,
    ) -> ResponseAnalysis:
        """
        Analyze an insurer response.

        Args:
            response_text: The new response email text.
            previous_responses: List of previous response texts.
            case_context: Optional case context for LLM analysis.

        Returns:
            ResponseAnalysis with detection results.
        """
        previous = previous_responses or self._response_history

        # Normalize text for comparison
        normalized = self._normalize_text(response_text)

        # Check for template phrases
        template_matches = self._detect_template_phrases(normalized)
        progress_matches = self._detect_progress_phrases(normalized)

        # Calculate similarity to previous responses
        max_similarity = 0.0
        for prev in previous:
            similarity = self._calculate_similarity(normalized, self._normalize_text(prev))
            max_similarity = max(max_similarity, similarity)

        # Determine if templated
        is_templated = (
            max_similarity >= self.similarity_threshold
            or len(template_matches) >= 2
        )

        # Check for escalation blocking language
        escalation_blocked = self._check_escalation_blocked(normalized)

        # Determine recommendation
        if progress_matches and not is_templated:
            recommendation = "positive_progress"
            explanation = "Response indicates case is being reviewed or escalated."
        elif is_templated and not progress_matches:
            recommendation = "auto_escalate"
            explanation = f"Response is {max_similarity:.0%} similar to previous. Auto-escalation recommended."
        else:
            recommendation = "manual_review"
            explanation = "Mixed signals detected. Manual review recommended."

        # LLM analysis for deeper insight (if available)
        new_points = []
        if self.llm_client and case_context:
            try:
                llm_analysis = self._llm_analyze(response_text, previous, case_context)
                new_points = llm_analysis.get("new_points", [])
                if llm_analysis.get("is_substantive"):
                    recommendation = "manual_review"
                    explanation = llm_analysis.get("explanation", explanation)
            except Exception as e:
                logger.warning(f"LLM analysis failed: {e}")

        # Store in history
        self._response_history.append(response_text)

        return ResponseAnalysis(
            is_templated=is_templated,
            similarity_to_previous=max_similarity,
            new_points_addressed=new_points,
            recommendation=recommendation,
            key_phrases_detected=template_matches + progress_matches,
            escalation_blocked=escalation_blocked,
            explanation=explanation,
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        # Lowercase
        text = text.lower()
        # Remove dates (various formats)
        text = re.sub(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', '', text)
        text = re.sub(r'\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{2,4}', '', text, flags=re.IGNORECASE)
        # Remove reference numbers
        text = re.sub(r'(?:ref|claim|policy|ticket)[:\s#]*[\w\-]+', '', text, flags=re.IGNORECASE)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity using SequenceMatcher."""
        return SequenceMatcher(None, text1, text2).ratio()

    def _detect_template_phrases(self, text: str) -> list[str]:
        """Detect common templated phrases."""
        found = []
        for phrase in self.TEMPLATE_PHRASES:
            if phrase in text:
                found.append(phrase)
        return found

    def _detect_progress_phrases(self, text: str) -> list[str]:
        """Detect phrases indicating positive progress."""
        found = []
        for phrase in self.PROGRESS_PHRASES:
            if phrase in text:
                found.append(phrase)
        return found

    def _check_escalation_blocked(self, text: str) -> bool:
        """Check if response indicates no further escalation possible."""
        blocking_phrases = [
            "final decision",
            "no further action",
            "case is closed",
            "matter is concluded",
            "approach the ombudsman",  # This actually means go external
        ]
        return any(phrase in text for phrase in blocking_phrases)

    def _llm_analyze(
        self,
        response_text: str,
        previous_responses: list[str],
        case_context: str,
    ) -> dict:
        """Use LLM to analyze response substance."""
        prompt = f"""Analyze this insurance company response to a claim escalation.

CASE CONTEXT:
{case_context}

PREVIOUS RESPONSES:
{chr(10).join([f'--- Response {i+1} ---{chr(10)}{r[:500]}...' for i, r in enumerate(previous_responses[-3:])])}

NEW RESPONSE:
{response_text}

Analyze and respond in JSON:
{{
    "is_substantive": true/false (does it add new information or just repeat?),
    "new_points": ["list of any new points addressed"],
    "explanation": "brief explanation of your assessment"
}}"""

        response = self.llm_client.generate(
            prompt=prompt,
            model=self.llm_client.MODELS["fast"],
            temperature=0.1,
        )

        import json
        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```\w*\n?', '', cleaned)
                cleaned = re.sub(r'```$', '', cleaned)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"is_substantive": False, "new_points": [], "explanation": "Analysis failed"}

    def get_content_hash(self, text: str) -> str:
        """Generate a hash of normalized content."""
        normalized = self._normalize_text(text)
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def clear_history(self) -> None:
        """Clear response history."""
        self._response_history.clear()
