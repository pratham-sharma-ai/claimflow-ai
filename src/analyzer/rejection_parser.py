"""
Rejection Parser for ClaimFlow AI.

Parses rejection emails to extract structured information
about the rejection reason, cited conditions, and clauses.
"""

import re
from dataclasses import dataclass
from typing import Optional

from ..llm.gemini_client import GeminiClient
from ..utils.logger import get_logger

logger = get_logger("claimflow.parser")


@dataclass
class ParsedRejection:
    """Structured rejection data."""
    rejection_type: str  # non_disclosure, pre_existing, documentation, policy_exclusion, other
    stated_reason: str
    conditions_cited: list[str]
    clauses_cited: list[str]
    documents_requested: list[str]
    causality_established: bool
    template_detected: bool
    weak_points: list[str]
    raw_text: str


class RejectionParser:
    """
    Parses rejection emails to extract structured data.

    Uses a combination of regex patterns and LLM analysis.
    """

    # Common rejection patterns
    REJECTION_PATTERNS = {
        "non_disclosure": [
            r"non[- ]?disclosure",
            r"failed to disclose",
            r"did not declare",
            r"material fact.*not disclosed",
        ],
        "pre_existing": [
            r"pre[- ]?existing",
            r"prior condition",
            r"previous medical history",
            r"already suffering",
        ],
        "documentation": [
            r"documents.*incomplete",
            r"required documents.*not submitted",
            r"additional documents.*required",
        ],
        "policy_exclusion": [
            r"excluded.*policy",
            r"not covered",
            r"exclusion clause",
            r"waiting period",
        ],
        "claim_period": [
            r"within.*days",
            r"delayed.*intimation",
            r"late.*claim",
        ],
    }

    def __init__(self, llm_client: GeminiClient | None = None):
        """
        Initialize parser.

        Args:
            llm_client: Optional Gemini client for LLM-based parsing.
        """
        self.llm_client = llm_client

    def parse(self, rejection_email: str, case_context: dict | None = None) -> ParsedRejection:
        """
        Parse a rejection email.

        Args:
            rejection_email: Raw rejection email text.
            case_context: Optional case context for better analysis.

        Returns:
            ParsedRejection with extracted data.
        """
        # First, try regex-based extraction
        rejection_type = self._detect_rejection_type(rejection_email)
        clauses = self._extract_clauses(rejection_email)
        documents = self._extract_document_requests(rejection_email)
        conditions = self._extract_conditions(rejection_email)

        # Use LLM for deeper analysis if available
        if self.llm_client:
            try:
                llm_result = self.llm_client.analyze_rejection(
                    rejection_email,
                    str(case_context) if case_context else "",
                )

                return ParsedRejection(
                    rejection_type=llm_result.get("rejection_type", rejection_type),
                    stated_reason=llm_result.get("stated_reason", ""),
                    conditions_cited=llm_result.get("conditions_cited", conditions) or conditions,
                    clauses_cited=llm_result.get("clauses_cited", clauses) or clauses,
                    documents_requested=llm_result.get("documents_requested", documents) or documents,
                    causality_established=llm_result.get("causality_established", False),
                    template_detected=self._is_template(rejection_email),
                    weak_points=llm_result.get("weak_points", []) or [],
                    raw_text=rejection_email,
                )
            except Exception as e:
                logger.warning(f"LLM parsing failed, using regex only: {e}")

        # Fallback to regex-only parsing
        return ParsedRejection(
            rejection_type=rejection_type,
            stated_reason=self._extract_reason(rejection_email),
            conditions_cited=conditions,
            clauses_cited=clauses,
            documents_requested=documents,
            causality_established=False,  # Can't determine without LLM
            template_detected=self._is_template(rejection_email),
            weak_points=[],
            raw_text=rejection_email,
        )

    def _detect_rejection_type(self, text: str) -> str:
        """Detect the type of rejection."""
        text_lower = text.lower()

        for rejection_type, patterns in self.REJECTION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return rejection_type

        return "other"

    def _extract_clauses(self, text: str) -> list[str]:
        """Extract cited policy clauses."""
        clauses = []

        # Common patterns for clause citations
        patterns = [
            r"clause\s+(\d+(?:\.\d+)*)",
            r"section\s+(\d+(?:\.\d+)*)",
            r"article\s+(\d+(?:\.\d+)*)",
            r"para(?:graph)?\s+(\d+(?:\.\d+)*)",
            r"condition\s+(\d+(?:\.\d+)*)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text.lower())
            clauses.extend([f"Clause {m}" for m in matches])

        return list(set(clauses))

    def _extract_document_requests(self, text: str) -> list[str]:
        """Extract requested documents."""
        documents = []

        # Common document types
        doc_patterns = [
            r"(medical records?)",
            r"(discharge summary)",
            r"(hospital bills?)",
            r"(doctor.s certificate)",
            r"(prescription)",
            r"(investigation reports?)",
            r"(lab reports?)",
            r"(previous treatment records?)",
            r"(pharmacy bills?)",
        ]

        text_lower = text.lower()
        for pattern in doc_patterns:
            if re.search(pattern, text_lower):
                match = re.search(pattern, text_lower)
                if match:
                    documents.append(match.group(1).title())

        return list(set(documents))

    def _extract_conditions(self, text: str) -> list[str]:
        """Extract medical conditions mentioned."""
        conditions = []

        # Common medical conditions
        condition_patterns = [
            r"(diabetes)",
            r"(hypertension)",
            r"(blood pressure)",
            r"(heart disease)",
            r"(cardiac)",
            r"(thyroid)",
            r"(asthma)",
            r"(kidney)",
            r"(liver)",
            r"(cancer)",
            r"(stroke)",
            r"(cholesterol)",
        ]

        text_lower = text.lower()
        for pattern in condition_patterns:
            if re.search(pattern, text_lower):
                match = re.search(pattern, text_lower)
                if match:
                    conditions.append(match.group(1).title())

        return list(set(conditions))

    def _extract_reason(self, text: str) -> str:
        """Extract the main stated reason."""
        # Look for common reason phrases
        patterns = [
            r"claim.*rejected.*(?:due to|because|as|for)\s+(.+?)(?:\.|$)",
            r"(?:reason|grounds?).*rejection[:\s]+(.+?)(?:\.|$)",
            r"unable to.*(?:process|approve).*(?:due to|because)\s+(.+?)(?:\.|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text.lower(), re.IGNORECASE | re.DOTALL)
            if match:
                reason = match.group(1).strip()
                # Clean up and limit length
                reason = re.sub(r'\s+', ' ', reason)[:200]
                return reason

        return "Reason not clearly stated"

    def _is_template(self, text: str) -> bool:
        """Check if the email appears to be a template."""
        template_indicators = [
            r"\[.*?\]",  # Placeholder brackets
            r"<.*?>",  # HTML-like placeholders
            r"dear\s+(?:sir|madam|customer)",
            r"we regret to inform",
            r"as per our records",
            r"thank you for your patience",
        ]

        text_lower = text.lower()
        matches = sum(1 for p in template_indicators if re.search(p, text_lower))

        return matches >= 2
