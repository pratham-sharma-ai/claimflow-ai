"""
Microsoft Outlook Client for ClaimFlow AI.

Uses MSAL (Microsoft Authentication Library) + Microsoft Graph API
to connect to personal Outlook.com / Hotmail accounts.

Authentication: Device Code Flow (user opens browser, enters code).
Token is cached locally so re-authentication is rarely needed.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

import msal
import httpx

from ..utils.logger import get_logger
from ..utils.config import get_project_root

logger = get_logger("claimflow.outlook")

GRAPH_API = "https://graph.microsoft.com/v1.0"


@dataclass
class OutlookEmail:
    """Represents an email from Outlook."""
    id: str
    message_id: str
    conversation_id: str
    from_name: str
    from_address: str
    to_addresses: list[str]
    subject: str
    body_preview: str
    body: str
    received_date: str
    is_read: bool
    has_attachments: bool
    importance: str

    @property
    def received_datetime(self) -> datetime:
        """Parse received date to datetime."""
        try:
            return datetime.fromisoformat(self.received_date.replace("Z", "+00:00"))
        except Exception:
            return datetime.min


class OutlookClient:
    """
    Microsoft Outlook client using MSAL + Graph API.

    Supports personal Outlook.com / Hotmail / Live.com accounts
    via the Device Code Flow.

    Setup required:
    1. Register an app at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
    2. Set "Supported account types" to include personal Microsoft accounts
    3. Enable "Allow public client flows"
    4. Add delegated permissions: Mail.Read, Mail.Send, User.Read
    5. Copy the Application (client) ID to your .env file
    """

    # Default scopes for email access
    SCOPES = ["Mail.Read", "Mail.Send", "User.Read"]

    # Authority for personal Microsoft accounts
    AUTHORITY = "https://login.microsoftonline.com/consumers"

    def __init__(
        self,
        client_id: str | None = None,
        cache_path: Path | None = None,
    ):
        """
        Initialize Outlook client.

        Args:
            client_id: Azure App Registration client ID.
                       Falls back to OUTLOOK_CLIENT_ID env var.
            cache_path: Path to token cache file.
        """
        self.client_id = client_id or os.getenv("OUTLOOK_CLIENT_ID")
        if not self.client_id:
            raise ValueError(
                "Outlook client ID required. Register an app at "
                "https://portal.azure.com and set OUTLOOK_CLIENT_ID env var.\n\n"
                "Steps:\n"
                "1. Go to Azure Portal > App Registrations > New Registration\n"
                "2. Name: 'ClaimFlow AI'\n"
                "3. Supported account types: 'Personal Microsoft accounts only'\n"
                "4. Redirect URI: leave blank\n"
                "5. After creation, go to Authentication > Allow public client flows > Yes\n"
                "6. Go to API Permissions > Add > Microsoft Graph > Delegated:\n"
                "   - Mail.Read, Mail.Send, User.Read\n"
                "7. Copy Application (client) ID to .env as OUTLOOK_CLIENT_ID"
            )

        # Token cache for persistence
        self.cache_path = cache_path or get_project_root() / ".token_cache.json"
        self._token_cache = msal.SerializableTokenCache()
        self._load_cache()

        # Initialize MSAL app
        self._app = msal.PublicClientApplication(
            self.client_id,
            authority=self.AUTHORITY,
            token_cache=self._token_cache,
        )

        self._access_token: str | None = None
        self._http = httpx.Client(timeout=30.0)

    def authenticate(self) -> bool:
        """
        Authenticate using Device Code Flow.

        First checks cache for existing token. If not found,
        initiates device code flow (user opens browser).

        Returns:
            True if authentication successful.
        """
        # Try to get token from cache first
        accounts = self._app.get_accounts()
        if accounts:
            logger.info(f"Found cached account: {accounts[0].get('username', 'unknown')}")
            result = self._app.acquire_token_silent(self.SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                self._save_cache()
                logger.info("Authenticated from cache (no login needed)")
                return True

        # No cached token - initiate device code flow
        flow = self._app.initiate_device_flow(scopes=self.SCOPES)
        if "user_code" not in flow:
            logger.error(f"Failed to create device flow: {flow}")
            return False

        # Display instructions to user
        print("\n" + "=" * 60)
        print("AUTHENTICATION REQUIRED")
        print("=" * 60)
        print(f"\n1. Open this URL in your browser:")
        print(f"   {flow['verification_uri']}")
        print(f"\n2. Enter this code: {flow['user_code']}")
        print(f"\n3. Sign in with your Outlook/Hotmail account")
        print("\nWaiting for authentication...")
        print("=" * 60 + "\n")

        # Wait for user to authenticate
        result = self._app.acquire_token_by_device_flow(flow)

        if "access_token" in result:
            self._access_token = result["access_token"]
            self._save_cache()
            username = result.get("id_token_claims", {}).get("preferred_username", "unknown")
            logger.info(f"Authenticated successfully as: {username}")
            return True
        else:
            error = result.get("error_description", result.get("error", "Unknown error"))
            logger.error(f"Authentication failed: {error}")
            return False

    def get_profile(self) -> dict:
        """Get the authenticated user's profile."""
        return self._graph_get("/me")

    def fetch_emails(
        self,
        folder: str = "inbox",
        top: int = 50,
        filter_from: str | None = None,
        filter_subject: str | None = None,
        since_date: datetime | None = None,
        fetch_all: bool = False,
    ) -> list[OutlookEmail]:
        """
        Fetch emails from Outlook.

        Args:
            folder: Mail folder (inbox, sentitems, drafts, etc.)
            top: Maximum emails per page.
            filter_from: Filter by sender address/name.
            filter_subject: Filter by subject content.
            since_date: Only fetch emails after this date.
            fetch_all: If True, paginate through all results.

        Returns:
            List of OutlookEmail objects.
        """
        # Build OData filter
        filters = []
        if filter_from:
            filters.append(f"contains(from/emailAddress/address,'{filter_from}') or contains(from/emailAddress/name,'{filter_from}')")
        if filter_subject:
            filters.append(f"contains(subject,'{filter_subject}')")
        if since_date:
            date_str = since_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            filters.append(f"receivedDateTime ge {date_str}")

        # Build query
        params = {
            "$top": str(top),
            "$orderby": "receivedDateTime desc",
            "$select": "id,internetMessageId,conversationId,from,toRecipients,subject,bodyPreview,body,receivedDateTime,isRead,hasAttachments,importance",
        }
        if filters:
            params["$filter"] = " and ".join(filters)

        # Fetch
        all_emails = []
        endpoint = f"/me/mailFolders/{folder}/messages"

        while endpoint:
            result = self._graph_get(endpoint, params=params)

            for msg in result.get("value", []):
                all_emails.append(self._parse_email(msg))

            # Handle pagination
            if fetch_all and "@odata.nextLink" in result:
                endpoint = result["@odata.nextLink"].replace(GRAPH_API, "")
                params = {}  # Params are in the nextLink URL
            else:
                endpoint = None

        logger.info(f"Fetched {len(all_emails)} emails from {folder}")
        return all_emails

    def fetch_emails_from_sender(
        self,
        sender: str,
        limit: int = 100,
    ) -> list[OutlookEmail]:
        """
        Fetch all emails from a specific sender.

        Args:
            sender: Sender email address or name to filter by.
            limit: Maximum emails to fetch.

        Returns:
            List of emails from that sender.
        """
        return self.fetch_emails(
            filter_from=sender,
            top=min(limit, 50),
            fetch_all=limit > 50,
        )

    def fetch_sent_emails(
        self,
        to_address: str | None = None,
        limit: int = 50,
    ) -> list[OutlookEmail]:
        """
        Fetch sent emails.

        Args:
            to_address: Filter by recipient address.
            limit: Maximum emails to fetch.

        Returns:
            List of sent emails.
        """
        emails = self.fetch_emails(folder="sentitems", top=limit)
        if to_address:
            to_lower = to_address.lower()
            emails = [
                e for e in emails
                if any(to_lower in addr.lower() for addr in e.to_addresses)
            ]
        return emails

    def search_emails(
        self,
        query: str,
        top: int = 50,
    ) -> list[OutlookEmail]:
        """
        Search emails using Microsoft Graph search.

        Args:
            query: Search query string.
            top: Maximum results.

        Returns:
            List of matching emails.
        """
        params = {
            "$search": f'"{query}"',
            "$top": str(top),
            "$select": "id,internetMessageId,conversationId,from,toRecipients,subject,bodyPreview,body,receivedDateTime,isRead,hasAttachments,importance",
        }

        result = self._graph_get("/me/messages", params=params)
        return [self._parse_email(msg) for msg in result.get("value", [])]

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_id: str | None = None,
    ) -> bool:
        """
        Send an email.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Email body (plain text).
            reply_to_id: Graph message ID to reply to (for threading).

        Returns:
            True if sent successfully.
        """
        if reply_to_id:
            # Reply to existing email
            payload = {
                "message": {
                    "toRecipients": [{"emailAddress": {"address": to}}],
                },
                "comment": body,
            }
            self._graph_post(f"/me/messages/{reply_to_id}/reply", payload)
        else:
            # New email
            payload = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                },
                "saveToSentItems": True,
            }
            self._graph_post("/me/sendMail", payload)

        logger.info(f"Email sent to {to}: {subject}")
        return True

    def _parse_email(self, msg: dict) -> OutlookEmail:
        """Parse Graph API email response into OutlookEmail."""
        from_data = msg.get("from", {}).get("emailAddress", {})
        to_data = msg.get("toRecipients", [])
        body_data = msg.get("body", {})

        return OutlookEmail(
            id=msg.get("id", ""),
            message_id=msg.get("internetMessageId", ""),
            conversation_id=msg.get("conversationId", ""),
            from_name=from_data.get("name", ""),
            from_address=from_data.get("address", ""),
            to_addresses=[
                r.get("emailAddress", {}).get("address", "")
                for r in to_data
            ],
            subject=msg.get("subject", ""),
            body_preview=msg.get("bodyPreview", ""),
            body=body_data.get("content", ""),
            received_date=msg.get("receivedDateTime", ""),
            is_read=msg.get("isRead", False),
            has_attachments=msg.get("hasAttachments", False),
            importance=msg.get("importance", "normal"),
        )

    def _graph_get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a GET request to Microsoft Graph API."""
        if not self._access_token:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        url = f"{GRAPH_API}{endpoint}" if not endpoint.startswith("http") else endpoint
        response = self._http.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {self._access_token}"},
        )

        if response.status_code == 401:
            # Token expired, re-authenticate
            logger.warning("Token expired, re-authenticating...")
            if self.authenticate():
                return self._graph_get(endpoint, params)
            raise RuntimeError("Re-authentication failed")

        response.raise_for_status()
        return response.json()

    def _graph_post(self, endpoint: str, payload: dict) -> dict | None:
        """Make a POST request to Microsoft Graph API."""
        if not self._access_token:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        url = f"{GRAPH_API}{endpoint}"
        response = self._http.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
        )

        if response.status_code == 401:
            logger.warning("Token expired, re-authenticating...")
            if self.authenticate():
                return self._graph_post(endpoint, payload)
            raise RuntimeError("Re-authentication failed")

        response.raise_for_status()

        if response.status_code == 202 or not response.content:
            return None
        return response.json()

    def _load_cache(self) -> None:
        """Load token cache from file."""
        if self.cache_path.exists():
            self._token_cache.deserialize(self.cache_path.read_text())
            logger.debug("Token cache loaded")

    def _save_cache(self) -> None:
        """Save token cache to file."""
        if self._token_cache.has_state_changed:
            self.cache_path.write_text(self._token_cache.serialize())
            logger.debug("Token cache saved")

    def close(self) -> None:
        """Close HTTP client and save cache."""
        self._save_cache()
        self._http.close()
        logger.debug("Outlook client closed")

    def __enter__(self):
        self.authenticate()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
