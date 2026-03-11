"""
Precedent Matcher for ClaimFlow AI.

Finds relevant precedents for a given rejection case
using semantic search and filtering.
"""

from dataclasses import dataclass

from ..knowledge.vector_store import VectorStore
from ..utils.logger import get_logger

logger = get_logger("claimflow.matcher")


@dataclass
class MatchedPrecedent:
    """A matched precedent with relevance info."""
    id: str
    title: str
    summary: str
    key_ruling: str
    source_url: str
    source: str
    relevance_score: float
    applicable_reason: str


class PrecedentMatcher:
    """
    Matches case details to relevant precedents.

    Uses the vector store for semantic search and applies
    additional filtering logic.
    """

    def __init__(self, vector_store: VectorStore):
        """
        Initialize matcher.

        Args:
            vector_store: Vector store with precedent embeddings.
        """
        self.vector_store = vector_store

    def find_matches(
        self,
        rejection_type: str,
        condition_claimed: str,
        condition_cited: str | None = None,
        stated_reason: str | None = None,
        top_k: int = 5,
    ) -> list[MatchedPrecedent]:
        """
        Find precedents matching the rejection details.

        Args:
            rejection_type: Type of rejection (non_disclosure, pre_existing, etc.)
            condition_claimed: Medical condition being claimed.
            condition_cited: Pre-existing condition cited by insurer.
            stated_reason: Full stated reason for rejection.
            top_k: Number of matches to return.

        Returns:
            List of matched precedents sorted by relevance.
        """
        # Build search query
        query_parts = []

        # Core query based on rejection type
        if rejection_type == "non_disclosure":
            query_parts.append("insurance claim rejected non-disclosure pre-existing condition")
            if condition_cited:
                query_parts.append(f"unrelated condition {condition_cited}")
        elif rejection_type == "pre_existing":
            query_parts.append("pre-existing condition claim rejection overturned")
        elif rejection_type == "documentation":
            query_parts.append("insurance claim document requirements")
        else:
            query_parts.append("insurance claim rejection appeal successful")

        # Add claimed condition
        query_parts.append(f"claim for {condition_claimed}")

        # Add stated reason if available
        if stated_reason:
            query_parts.append(stated_reason[:100])

        query = " ".join(query_parts)

        # Determine filter tags
        filter_tags = self._get_filter_tags(rejection_type, condition_cited)

        # Search vector store
        results = self.vector_store.search(
            query=query,
            top_k=top_k * 2,  # Get more, then filter
            filter_tags=filter_tags if filter_tags else None,
        )

        # Convert to MatchedPrecedent and filter
        matched = []
        for result in results:
            relevance_reason = self._explain_relevance(
                result, rejection_type, condition_claimed, condition_cited
            )

            if result.get("relevance_score", 0) < 0.3:
                continue  # Skip low relevance matches

            matched.append(MatchedPrecedent(
                id=result["id"],
                title=result.get("title", ""),
                summary=result.get("summary", ""),
                key_ruling=result.get("key_ruling", ""),
                source_url=result.get("source_url", ""),
                source=result.get("source", ""),
                relevance_score=result.get("relevance_score", 0),
                applicable_reason=relevance_reason,
            ))

        # Sort by relevance and return top_k
        matched.sort(key=lambda x: x.relevance_score, reverse=True)
        return matched[:top_k]

    def find_for_rejection(
        self,
        parsed_rejection: "ParsedRejection",  # noqa: F821
        case_data: dict,
    ) -> list[MatchedPrecedent]:
        """
        Find precedents for a parsed rejection.

        Args:
            parsed_rejection: ParsedRejection object.
            case_data: Case data dictionary.

        Returns:
            List of matched precedents.
        """
        condition_claimed = case_data.get("claim", {}).get("condition", "")
        condition_cited = None
        if parsed_rejection.conditions_cited:
            condition_cited = ", ".join(parsed_rejection.conditions_cited)

        return self.find_matches(
            rejection_type=parsed_rejection.rejection_type,
            condition_claimed=condition_claimed,
            condition_cited=condition_cited,
            stated_reason=parsed_rejection.stated_reason,
        )

    def _get_filter_tags(
        self,
        rejection_type: str,
        condition_cited: str | None,
    ) -> list[str]:
        """Get filter tags based on rejection details."""
        tags = []

        if rejection_type == "non_disclosure":
            tags.extend(["non-disclosure", "non_disclosure"])
        if rejection_type == "pre_existing":
            tags.extend(["pre-existing", "pre_existing"])
        if condition_cited:
            tags.append("unrelated-condition")

        # Always include general tags
        tags.extend(["ombudsman-ruling", "irdai-guideline", "claim-settlement"])

        return tags

    def _explain_relevance(
        self,
        result: dict,
        rejection_type: str,
        condition_claimed: str,
        condition_cited: str | None,
    ) -> str:
        """Generate explanation for why precedent is relevant."""
        title = result.get("title", "").lower()
        summary = result.get("summary", "").lower()
        tags = result.get("tags", [])

        reasons = []

        # Check for matching rejection type
        if rejection_type in str(tags) or rejection_type.replace("_", "-") in str(tags):
            reasons.append(f"Matches rejection type: {rejection_type}")

        # Check for unrelated condition ruling
        if "unrelated" in summary or "no causal link" in summary:
            reasons.append("Supports argument that conditions are unrelated")

        # Check for ombudsman ruling
        if "ombudsman" in title or "ombudsman" in summary:
            reasons.append("Ombudsman ruling (strong precedent)")

        # Check for IRDAI reference
        if "irdai" in title or "irdai" in summary:
            reasons.append("References IRDAI guidelines")

        if not reasons:
            reasons.append("General insurance claim precedent")

        return "; ".join(reasons)

    def format_for_email(
        self,
        precedents: list[MatchedPrecedent],
        max_precedents: int = 3,
    ) -> str:
        """
        Format precedents for inclusion in escalation email.

        Args:
            precedents: List of matched precedents.
            max_precedents: Maximum to include.

        Returns:
            Formatted string for email.
        """
        if not precedents:
            return "No specific precedents found, but IRDAI guidelines support the claimant's position."

        lines = []
        for i, p in enumerate(precedents[:max_precedents], 1):
            lines.append(f"{i}. {p.title}")
            lines.append(f"   Ruling: {p.key_ruling}")
            if p.source_url:
                lines.append(f"   Source: {p.source_url}")
            lines.append(f"   Relevance: {p.applicable_reason}")
            lines.append("")

        return "\n".join(lines)
