"""Escalation module - email handling and response detection."""

from .email_client import YahooEmailClient
from .drafter import EscalationDrafter
from .response_detector import ResponseDetector

__all__ = ["YahooEmailClient", "EscalationDrafter", "ResponseDetector"]
