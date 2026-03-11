"""
Email Repetition Analyzer for ClaimFlow AI.

Analyzes email threads with insurers to detect:
- Repeated/templated responses
- Response time patterns
- Escalation blockers
- Timeline of interactions
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from ..escalation.email_client import Email
from ..utils.logger import get_logger

logger = get_logger("claimflow.email_analyzer")


@dataclass
class EmailGroup:
    """A group of similar/identical emails."""
    content_hash: str
    emails: list[Email]
    representative_subject: str
    representative_body_preview: str
    count: int = 0
    first_seen: str = ""
    last_seen: str = ""

    def __post_init__(self):
        self.count = len(self.emails)
        if self.emails:
            dates = sorted(self.emails, key=lambda e: e.date)
            self.first_seen = dates[0].date
            self.last_seen = dates[-1].date


@dataclass
class TimelineEntry:
    """A single entry in the communication timeline."""
    date: str
    direction: str  # "incoming" or "outgoing"
    subject: str
    body_preview: str
    from_address: str
    is_templated: bool
    content_hash: str
    response_time_hours: float | None = None  # Hours since last email in opposite direction


@dataclass
class AnalysisResult:
    """Complete analysis of email communication."""
    total_emails_received: int
    total_emails_sent: int
    unique_responses: int
    repeated_responses: int
    repetition_rate: float  # 0-1, what % of responses are repeats
    avg_response_time_hours: float
    max_response_gap_days: float
    timeline: list[TimelineEntry]
    email_groups: list[EmailGroup]
    template_phrases_found: dict[str, int]  # phrase -> count
    first_email_date: str
    last_email_date: str
    total_days_elapsed: int
    insurer_name: str
    key_findings: list[str]


class EmailAnalyzer:
    """
    Analyzes email threads to detect repetition patterns
    and build communication timelines.
    """

    # Common template phrases insurers use
    TEMPLATE_INDICATORS = [
        "we regret to inform",
        "as per our records",
        "your claim has been reviewed",
        "after careful consideration",
        "we are unable to process",
        "as mentioned in our previous",
        "our decision remains unchanged",
        "please refer to the policy terms",
        "the claim stands rejected",
        "thank you for your patience",
        "we appreciate your understanding",
        "we have already communicated",
    ]

    def __init__(self, similarity_threshold: float = 0.80):
        """
        Initialize analyzer.

        Args:
            similarity_threshold: Threshold for considering responses "same" (0-1).
        """
        self.similarity_threshold = similarity_threshold

    def analyze(
        self,
        received_emails: list[Email],
        sent_emails: list[Email],
        insurer_name: str = "Insurer",
    ) -> AnalysisResult:
        """
        Analyze email communication with an insurer.

        Args:
            received_emails: Emails received FROM the insurer.
            sent_emails: Emails sent TO the insurer.
            insurer_name: Name of the insurer for reporting.

        Returns:
            Complete AnalysisResult.
        """
        # Build timeline
        timeline = self._build_timeline(received_emails, sent_emails)

        # Group similar received emails
        groups = self._group_similar_emails(received_emails)

        # Calculate repetition stats
        unique_count = len(groups)
        total_received = len(received_emails)
        repeated_count = total_received - unique_count
        repetition_rate = repeated_count / total_received if total_received > 0 else 0

        # Calculate response times
        response_times = self._calculate_response_times(timeline)
        avg_response_time = (
            sum(response_times) / len(response_times) if response_times else 0
        )

        # Find max gap
        max_gap = self._calculate_max_gap(timeline)

        # Detect template phrases
        template_phrases = self._detect_all_template_phrases(received_emails)

        # Date range
        all_dates = [e.date for e in received_emails + sent_emails if e.date]
        all_dates.sort()
        first_date = all_dates[0] if all_dates else ""
        last_date = all_dates[-1] if all_dates else ""

        # Days elapsed
        days_elapsed = 0
        if first_date and last_date:
            try:
                d1 = datetime.fromisoformat(first_date.replace("Z", "+00:00"))
                d2 = datetime.fromisoformat(last_date.replace("Z", "+00:00"))
                days_elapsed = (d2 - d1).days
            except Exception:
                pass

        # Generate key findings
        findings = self._generate_findings(
            total_received, unique_count, repetition_rate,
            avg_response_time, template_phrases, groups, days_elapsed,
        )

        return AnalysisResult(
            total_emails_received=total_received,
            total_emails_sent=len(sent_emails),
            unique_responses=unique_count,
            repeated_responses=repeated_count,
            repetition_rate=repetition_rate,
            avg_response_time_hours=avg_response_time,
            max_response_gap_days=max_gap,
            timeline=timeline,
            email_groups=groups,
            template_phrases_found=template_phrases,
            first_email_date=first_date,
            last_email_date=last_date,
            total_days_elapsed=days_elapsed,
            insurer_name=insurer_name,
            key_findings=findings,
        )

    def _build_timeline(
        self,
        received: list[Email],
        sent: list[Email],
    ) -> list[TimelineEntry]:
        """Build chronological timeline of all communication."""
        timeline = []

        # Add received emails
        for email in received:
            content_hash = self._hash_content(email.body)
            is_templated = self._is_templated(email.body)

            timeline.append(TimelineEntry(
                date=email.date,
                direction="incoming",
                subject=email.subject,
                body_preview=email.body[:200],
                from_address=email.from_addr,
                is_templated=is_templated,
                content_hash=content_hash,
            ))

        # Add sent emails
        for email in sent:
            content_hash = self._hash_content(email.body)

            timeline.append(TimelineEntry(
                date=email.date,
                direction="outgoing",
                subject=email.subject,
                body_preview=email.body[:200],
                from_address=email.from_addr,
                is_templated=False,  # Our own emails aren't templated
                content_hash=content_hash,
            ))

        # Sort by date
        timeline.sort(key=lambda e: e.date)

        # Calculate response times
        for i, entry in enumerate(timeline):
            if i == 0:
                continue
            # Find previous email in opposite direction
            for j in range(i - 1, -1, -1):
                if timeline[j].direction != entry.direction:
                    try:
                        d1 = datetime.fromisoformat(timeline[j].date.replace("Z", "+00:00"))
                        d2 = datetime.fromisoformat(entry.date.replace("Z", "+00:00"))
                        hours = (d2 - d1).total_seconds() / 3600
                        entry.response_time_hours = round(hours, 1)
                    except Exception:
                        pass
                    break

        return timeline

    def _group_similar_emails(
        self,
        emails: list[Email],
    ) -> list[EmailGroup]:
        """Group emails with similar content together."""
        groups: dict[str, list[Email]] = {}

        for email in emails:
            text = email.body
            normalized = self._normalize_for_comparison(text)

            # Check if this matches any existing group
            matched_group = None
            for group_hash, group_emails in groups.items():
                representative = group_emails[0].body
                representative_norm = self._normalize_for_comparison(representative)

                similarity = SequenceMatcher(None, normalized, representative_norm).ratio()
                if similarity >= self.similarity_threshold:
                    matched_group = group_hash
                    break

            if matched_group:
                groups[matched_group].append(email)
            else:
                content_hash = self._hash_content(text)
                groups[content_hash] = [email]

        # Convert to EmailGroup objects
        result = []
        for hash_key, group_emails in groups.items():
            rep = group_emails[0]
            result.append(EmailGroup(
                content_hash=hash_key,
                emails=group_emails,
                representative_subject=rep.subject,
                representative_body_preview=rep.body[:300],
            ))

        # Sort: most repeated first
        result.sort(key=lambda g: g.count, reverse=True)
        return result

    def _normalize_for_comparison(self, text: str) -> str:
        """Normalize text for similarity comparison."""
        text = text.lower()
        # Remove dates
        text = re.sub(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', '', text)
        text = re.sub(
            r'\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{2,4}',
            '', text, flags=re.IGNORECASE
        )
        # Remove reference/claim numbers
        text = re.sub(r'(?:ref|claim|policy|ticket|case)[:\s#]*[\w\-]+', '', text, flags=re.IGNORECASE)
        # Remove extra whitespace and HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _hash_content(self, text: str) -> str:
        """Generate content hash for deduplication."""
        normalized = self._normalize_for_comparison(text)
        return hashlib.md5(normalized.encode()).hexdigest()[:12]

    def _is_templated(self, text: str) -> bool:
        """Check if text appears to be a templated response."""
        text_lower = text.lower()
        matches = sum(1 for phrase in self.TEMPLATE_INDICATORS if phrase in text_lower)
        return matches >= 2

    def _calculate_response_times(self, timeline: list[TimelineEntry]) -> list[float]:
        """Get list of response times (in hours) from insurer."""
        times = []
        for entry in timeline:
            if entry.direction == "incoming" and entry.response_time_hours is not None:
                times.append(entry.response_time_hours)
        return times

    def _calculate_max_gap(self, timeline: list[TimelineEntry]) -> float:
        """Calculate maximum gap (in days) between communications."""
        if len(timeline) < 2:
            return 0

        max_gap = 0
        for i in range(1, len(timeline)):
            try:
                d1 = datetime.fromisoformat(timeline[i-1].date.replace("Z", "+00:00"))
                d2 = datetime.fromisoformat(timeline[i].date.replace("Z", "+00:00"))
                gap_days = (d2 - d1).total_seconds() / 86400
                max_gap = max(max_gap, gap_days)
            except Exception:
                continue

        return round(max_gap, 1)

    def _detect_all_template_phrases(
        self,
        emails: list[Email],
    ) -> dict[str, int]:
        """Count template phrases across all received emails."""
        counter: Counter = Counter()

        for email in emails:
            text = email.body.lower()
            for phrase in self.TEMPLATE_INDICATORS:
                if phrase in text:
                    counter[phrase] += 1

        return dict(counter.most_common())

    def _generate_findings(
        self,
        total_received: int,
        unique_count: int,
        repetition_rate: float,
        avg_response_time: float,
        template_phrases: dict,
        groups: list[EmailGroup],
        days_elapsed: int,
    ) -> list[str]:
        """Generate human-readable key findings."""
        findings = []

        # Repetition finding
        if repetition_rate > 0.5:
            findings.append(
                f"{repetition_rate:.0%} of responses are duplicates. "
                f"Out of {total_received} emails received, only {unique_count} "
                f"contained unique content."
            )
        elif repetition_rate > 0.2:
            findings.append(
                f"{repetition_rate:.0%} of responses are near-identical repeats."
            )

        # Template detection
        if template_phrases:
            top_phrase = list(template_phrases.keys())[0]
            top_count = template_phrases[top_phrase]
            findings.append(
                f"The phrase \"{top_phrase}\" appeared in {top_count} emails, "
                f"indicating automated responses."
            )

        # Most repeated group
        if groups and groups[0].count > 1:
            findings.append(
                f"The most repeated response was sent {groups[0].count} times "
                f"between {groups[0].first_seen[:10]} and {groups[0].last_seen[:10]}."
            )

        # Response time
        if avg_response_time > 0:
            if avg_response_time > 168:  # More than a week
                findings.append(
                    f"Average insurer response time: {avg_response_time / 24:.0f} days."
                )
            else:
                findings.append(
                    f"Average insurer response time: {avg_response_time:.0f} hours."
                )

        # Duration
        if days_elapsed > 0:
            findings.append(
                f"Issue has been open for {days_elapsed} days with no resolution."
            )

        # No unique response check
        if unique_count <= 1 and total_received > 1:
            findings.append(
                "Every single response from the insurer is essentially the same email. "
                "No case-specific review has been conducted."
            )

        return findings
