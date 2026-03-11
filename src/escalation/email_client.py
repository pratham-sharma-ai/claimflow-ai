"""
Yahoo Mail Client for ClaimFlow AI.

Uses IMAP/SMTP with App Password authentication.
Handles sending escalation emails and monitoring responses.
"""

import imaplib
import smtplib
import os
import hashlib
from email import message_from_bytes
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid, parsedate_to_datetime
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from ..utils.logger import get_logger

logger = get_logger("claimflow.email")


@dataclass
class Email:
    """Represents an email message."""
    id: str
    message_id: str
    from_addr: str
    to_addr: str
    subject: str
    date: str
    body: str
    thread_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    content_hash: str = field(default="")

    def __post_init__(self):
        """Calculate content hash for duplicate detection."""
        if not self.content_hash:
            # Hash the body content (normalized)
            normalized = self.body.lower().strip()
            # Remove common variable parts (dates, reference numbers)
            import re
            normalized = re.sub(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', '', normalized)
            normalized = re.sub(r'ref[:\s#]*\w+', '', normalized, flags=re.IGNORECASE)
            self.content_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]


class YahooEmailClient:
    """
    Yahoo Mail client using App Password authentication.

    Supports:
    - Reading emails from inbox
    - Sending emails with proper threading
    - Searching for specific emails
    - Tracking email threads
    """

    IMAP_SERVER = "imap.mail.yahoo.com"
    IMAP_PORT = 993
    SMTP_SERVER = "smtp.mail.yahoo.com"
    SMTP_PORT = 465

    def __init__(
        self,
        email: str | None = None,
        app_password: str | None = None,
    ):
        """
        Initialize Yahoo Mail client.

        Args:
            email: Yahoo email address. Falls back to YAHOO_EMAIL env var.
            app_password: Yahoo app password. Falls back to YAHOO_APP_PASSWORD env var.
        """
        self.email = email or os.getenv("YAHOO_EMAIL")
        self.app_password = app_password or os.getenv("YAHOO_APP_PASSWORD")

        if not self.email or not self.app_password:
            raise ValueError(
                "Yahoo email and app password required. "
                "Set YAHOO_EMAIL and YAHOO_APP_PASSWORD env vars."
            )

        self._imap: imaplib.IMAP4_SSL | None = None
        self._smtp: smtplib.SMTP_SSL | None = None

        logger.info(f"Yahoo email client initialized for: {self.email}")

    def connect_imap(self) -> "YahooEmailClient":
        """Connect to Yahoo IMAP server."""
        try:
            self._imap = imaplib.IMAP4_SSL(self.IMAP_SERVER, self.IMAP_PORT)
            self._imap.login(self.email, self.app_password)
            logger.debug("IMAP connection established")
            return self
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP connection failed: {e}")
            raise

    def connect_smtp(self) -> "YahooEmailClient":
        """Connect to Yahoo SMTP server."""
        try:
            self._smtp = smtplib.SMTP_SSL(self.SMTP_SERVER, self.SMTP_PORT)
            self._smtp.login(self.email, self.app_password)
            logger.debug("SMTP connection established")
            return self
        except smtplib.SMTPException as e:
            logger.error(f"SMTP connection failed: {e}")
            raise

    def connect(self) -> "YahooEmailClient":
        """Connect to both IMAP and SMTP."""
        self.connect_imap()
        self.connect_smtp()
        return self

    def list_folders(self) -> list[str]:
        """List all available IMAP folders."""
        if not self._imap:
            self.connect_imap()

        status, folders = self._imap.list()
        result = []
        if status == "OK":
            for folder_info in folders:
                if isinstance(folder_info, bytes):
                    decoded = folder_info.decode("utf-8", errors="replace")
                    # Extract folder name from IMAP LIST response
                    # Format: (\\Flags) "delimiter" "folder_name"
                    parts = decoded.rsplit('"', 2)
                    if len(parts) >= 2:
                        result.append(parts[-2])
                    else:
                        result.append(decoded)
        logger.info(f"Available folders: {result}")
        return result

    def fetch_emails(
        self,
        folder: str = "INBOX",
        search_criteria: str = "ALL",
        limit: int = 20,
        since_date: datetime | None = None,
    ) -> list[Email]:
        """
        Fetch emails from a folder.

        Args:
            folder: Mailbox folder to search.
            search_criteria: IMAP search criteria (ALL, UNSEEN, FROM, SUBJECT, etc.)
            limit: Maximum emails to fetch.
            since_date: Only fetch emails after this date.

        Returns:
            List of Email objects.
        """
        if not self._imap:
            self.connect_imap()

        # Try selecting the folder
        status, data = self._imap.select(folder)
        if status != "OK":
            logger.warning(f"Failed to select folder '{folder}': {data}")
            # Try common alternative folder names
            alternatives = {
                "Sent": ["Sent", "Sent Messages", "Sent Items", "INBOX.Sent"],
                "Draft": ["Draft", "Drafts", "INBOX.Drafts"],
                "Trash": ["Trash", "Deleted", "Deleted Items", "INBOX.Trash"],
            }
            found = False
            for alt in alternatives.get(folder, []):
                if alt == folder:
                    continue
                status, data = self._imap.select(alt)
                if status == "OK":
                    logger.info(f"Using alternative folder: {alt}")
                    found = True
                    break
            if not found:
                logger.warning(f"Could not find folder '{folder}'. Available: {self.list_folders()}")
                return []

        # Build search criteria
        criteria = search_criteria
        if since_date:
            date_str = since_date.strftime("%d-%b-%Y")
            criteria = f'(SINCE {date_str}) {criteria}'

        status, messages = self._imap.search(None, criteria)
        if status != "OK":
            logger.warning(f"Search failed: {status}")
            return []

        email_ids = messages[0].split()
        # Get last N emails (most recent)
        email_ids = email_ids[-limit:] if len(email_ids) > limit else email_ids

        emails = []
        for eid in reversed(email_ids):  # Newest first
            try:
                status, msg_data = self._imap.fetch(eid, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                email_message = message_from_bytes(raw_email)

                # Parse date to ISO format for consistent handling
                raw_date = email_message.get("Date", "")
                try:
                    parsed_dt = parsedate_to_datetime(raw_date)
                    iso_date = parsed_dt.isoformat()
                except Exception:
                    iso_date = raw_date

                emails.append(Email(
                    id=eid.decode(),
                    message_id=email_message.get("Message-ID", ""),
                    from_addr=self._decode_header(email_message.get("From", "")),
                    to_addr=self._decode_header(email_message.get("To", "")),
                    subject=self._decode_header(email_message.get("Subject", "")),
                    date=iso_date,
                    body=self._extract_body(email_message),
                    in_reply_to=email_message.get("In-Reply-To"),
                    thread_id=email_message.get("References", "").split()[0] if email_message.get("References") else None,
                ))
            except Exception as e:
                logger.warning(f"Failed to fetch email {eid}: {e}")
                continue

        logger.info(f"Fetched {len(emails)} emails from {folder}")
        return emails

    def search_by_subject(
        self,
        subject_contains: str,
        folder: str = "INBOX",
        limit: int = 10,
    ) -> list[Email]:
        """
        Search emails by subject line.

        Args:
            subject_contains: Text to search in subject.
            folder: Mailbox folder to search.
            limit: Maximum emails to return.

        Returns:
            List of matching Email objects.
        """
        criteria = f'(SUBJECT "{subject_contains}")'
        return self.fetch_emails(folder=folder, search_criteria=criteria, limit=limit)

    def search_by_sender(
        self,
        from_address: str,
        folder: str = "INBOX",
        limit: int = 10,
    ) -> list[Email]:
        """
        Search emails by sender.

        Args:
            from_address: Sender email address or domain.
            folder: Mailbox folder to search.
            limit: Maximum emails to return.

        Returns:
            List of matching Email objects.
        """
        criteria = f'(FROM "{from_address}")'
        return self.fetch_emails(folder=folder, search_criteria=criteria, limit=limit)

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_message_id: str | None = None,
        cc: list[str] | None = None,
    ) -> str:
        """
        Send an email.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Email body (plain text).
            reply_to_message_id: Message-ID to reply to (for threading).
            cc: List of CC addresses.

        Returns:
            Message-ID of sent email.
        """
        if not self._smtp:
            self.connect_smtp()

        msg = MIMEMultipart()
        msg["From"] = self.email
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.email.split("@")[1])

        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
            msg["References"] = reply_to_message_id

        if cc:
            msg["Cc"] = ", ".join(cc)

        msg.attach(MIMEText(body, "plain"))

        try:
            recipients = [to] + (cc or [])
            self._smtp.send_message(msg)
            logger.info(f"Email sent to {to}: {subject}")
            return msg["Message-ID"]
        except smtplib.SMTPException as e:
            logger.error(f"Failed to send email: {e}")
            raise

    def send_escalation(
        self,
        to: str,
        claim_id: str,
        escalation_level: int,
        body: str,
        previous_message_id: str | None = None,
    ) -> str:
        """
        Send a formatted escalation email.

        Args:
            to: Insurer grievance email.
            claim_id: Claim reference number.
            escalation_level: Current escalation level.
            body: Email body content.
            previous_message_id: Previous email Message-ID for threading.

        Returns:
            Message-ID of sent email.
        """
        level_prefix = {
            1: "Follow-up",
            2: "Escalation - Senior Review Requested",
            3: "Final Notice - Pre-Legal",
        }
        prefix = level_prefix.get(escalation_level, f"Escalation Level {escalation_level}")

        subject = f"{prefix} - Claim #{claim_id}"

        return self.send_email(
            to=to,
            subject=subject,
            body=body,
            reply_to_message_id=previous_message_id,
        )

    def get_thread(self, message_id: str) -> list[Email]:
        """
        Get all emails in a thread.

        Args:
            message_id: Message-ID to find thread for.

        Returns:
            List of emails in the thread.
        """
        # Search for emails that reference this message
        criteria = f'(OR (HEADER "In-Reply-To" "{message_id}") (HEADER "References" "{message_id}"))'
        thread_emails = self.fetch_emails(search_criteria=criteria, limit=50)

        # Also get the original email
        original_criteria = f'(HEADER "Message-ID" "{message_id}")'
        original = self.fetch_emails(search_criteria=original_criteria, limit=1)

        all_emails = original + thread_emails
        # Sort by date
        all_emails.sort(key=lambda e: e.date)
        return all_emails

    @staticmethod
    def _decode_header(value: str) -> str:
        """Decode RFC 2047 encoded email headers."""
        if not value:
            return ""
        try:
            parts = _decode_header(value)
            decoded = []
            for part, encoding in parts:
                if isinstance(part, bytes):
                    decoded.append(part.decode(encoding or "utf-8", errors="replace"))
                else:
                    decoded.append(part)
            return " ".join(decoded)
        except Exception:
            return value

    def _extract_body(self, email_message) -> str:
        """Extract plain text body from email message."""
        body = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
                    except Exception:
                        continue
        else:
            try:
                payload = email_message.get_payload(decode=True)
                charset = email_message.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
            except Exception:
                body = str(email_message.get_payload())

        return body.strip()

    def close(self) -> None:
        """Close all connections."""
        if self._imap:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

        if self._smtp:
            try:
                self._smtp.quit()
            except Exception:
                pass
            self._smtp = None

        logger.debug("Email client connections closed")

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
