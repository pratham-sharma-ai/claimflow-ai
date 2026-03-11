"""Tests for Response Detector."""

import pytest
from src.escalation.response_detector import ResponseDetector, ResponseAnalysis


class TestResponseDetector:
    """Test suite for ResponseDetector."""

    def setup_method(self):
        """Set up test fixtures."""
        self.detector = ResponseDetector(llm_client=None, similarity_threshold=0.85)

    def test_detect_templated_response(self):
        """Should detect templated responses."""
        templated = """
        Dear Sir/Madam,

        We regret to inform you that your claim has been reviewed and
        as per our records, we are unable to process your request.

        Thank you for your patience.

        Regards,
        Claims Team
        """

        analysis = self.detector.analyze(templated)
        assert analysis.is_templated is True
        assert "we regret to inform" in analysis.key_phrases_detected

    def test_detect_progress_response(self):
        """Should detect positive progress."""
        progress = """
        Dear Mr. Sharma,

        Thank you for your continued correspondence. We have noted your concerns
        and your case has been escalated to senior management for review.

        Our medical board will review the case and we will revert within 7 days.

        Regards,
        Senior Claims Manager
        """

        analysis = self.detector.analyze(progress)
        assert "positive_progress" in analysis.recommendation or not analysis.is_templated

    def test_similarity_detection(self):
        """Should detect similar responses."""
        response1 = "Your claim has been rejected due to non-disclosure of pre-existing condition."
        response2 = "Your claim has been rejected due to non-disclosure of pre-existing condition."

        self.detector.analyze(response1)
        analysis = self.detector.analyze(response2, previous_responses=[response1])

        assert analysis.similarity_to_previous >= 0.85

    def test_escalation_blocked_detection(self):
        """Should detect when escalation is blocked."""
        blocked = """
        This is our final decision on the matter. No further action can be taken.
        The case is closed. You may approach the Insurance Ombudsman if desired.
        """

        analysis = self.detector.analyze(blocked)
        assert analysis.escalation_blocked is True
