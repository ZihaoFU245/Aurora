"""Gmail provider implementation.

This module implements :class:`GmailClient` which provides an asynchronous
wrapper around the Gmail API.  The class adheres to the
``AsyncEmailProvider`` interface defined in :mod:`EmailTools.abc`.

The implementation purposefully keeps the logic lightweight and relies on
``asyncio.to_thread`` to run the blocking Google API client in a thread.  The
configuration is sourced from :mod:`EmailTools.config` which exposes the
``Config`` object at package import time.

The class only implements a subset of the Gmail functionality required by the
abstract base class.  The methods cover common actions such as fetching unread
messages, sending mail, working with drafts and updating message state.  Each
method returns domain models defined in :mod:`EmailTools.models`.
"""

from __future__ import annotations

import asyncio
import base64
import os
from email.message import EmailMessage as _EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Any, Dict, List, Optional, Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..config import Config
from ..abc import AsyncEmailProvider, AddressListLike
from ..models import (
    AccountInfo,
    Attachment,
    Draft,
    EmailAddress,
    EmailMessage,
)


class GmailClient(AsyncEmailProvider):
    """Concrete :class:`AsyncEmailProvider` for Google's Gmail service."""

    #: Scopes used for Gmail access.  These provide read/write access as well as
    #: draft and send capabilities.
    SCOPES: Sequence[str] = (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.send",
    )

    #: Hard upper bound for number of emails fetched in a single call.  Values
    #: greater than this are clipped (never raise) to avoid huge responses.
    MAX_FETCH_RESULTS: int = 50

    def __init__(self, account: AccountInfo, secrets: Dict[str, str]):
        super().__init__(account, secrets)

        creds: Optional[Credentials] = None
        # Sanitize account name for filesystem safety
        safe_name = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in account.name)
        token_name = f"{safe_name}_gmail.json"
        token_path = (
            os.path.join(Config.TOKEN_PATH, token_name)
            if Config.TOKEN_PATH
            else token_name
        )
        # Ensure the token directory exists before attempting to read/write.
        token_dir = os.path.dirname(token_path)
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None
            if not creds or not creds.valid:
                # Validate credentials file path early for better error messages.
                cred_path = Config.GOOGLE_CREDENTIALS_PATH
                if not cred_path or not os.path.exists(cred_path):
                    raise FileNotFoundError(
                        f"GOOGLE_CREDENTIALS_PATH is not set or does not exist: {cred_path!r}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    cred_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            # Persist the refreshed/created credentials so the user does not
            # need to re-authenticate every run.
            with open(token_path, "w") as token_file:
                token_file.write(creds.to_json())

        # ``build`` creates a synchronous client – we will execute its calls in a
        # background thread using ``asyncio.to_thread``.
        self.service = build("gmail", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------
    def _parse_address(self, value: str) -> EmailAddress:
        name, email = parseaddr(value)
        return EmailAddress(email=email, name=name or None)

    def _parse_address_list(self, value: Optional[str]) -> List[EmailAddress]:
        if not value:
            return []
        return [
            EmailAddress(email=addr[1], name=addr[0] or None)
            for addr in getaddresses([value])
        ]

    def _extract_plain_body(self, payload: Dict[str, Any]) -> Optional[str]:
        """Return the plain text body from a Gmail API ``payload`` dict."""
        if "body" in payload and payload.get("mimeType") == "text/plain":
            data = payload["body"].get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        for part in payload.get("parts", []) or []:
            text = self._extract_plain_body(part)
            if text:
                return text
        return None

    def _build_message(
            self,
            *,
            to: AddressListLike,
            subject: str,
            body_text: str,
            cc: Optional[AddressListLike] = None,
            bcc: Optional[AddressListLike] = None,
            html_body: Optional[str] = None,
            attachments: Optional[Sequence[Attachment]] = None,
    ) -> _EmailMessage:
        def _fmt(a: Any) -> str:
            if isinstance(a, EmailAddress):
                return f"{a.name} <{a.email}>" if a.name else a.email
            return str(a)

        msg = _EmailMessage()
        msg["To"] = to if isinstance(to, str) else ", ".join(_fmt(a) for a in to)
        if cc:
            msg["Cc"] = cc if isinstance(cc, str) else ", ".join(_fmt(a) for a in cc)
        if bcc:
            msg["Bcc"] = bcc if isinstance(bcc, str) else ", ".join(_fmt(a) for a in bcc)
        msg["Subject"] = subject
        if html_body:
            msg.add_alternative(html_body, subtype="html")
            msg.set_content(body_text)
        else:
            msg.set_content(body_text)

        # Attachments
        for attachment in attachments or []:
            if attachment.file_path:
                with open(attachment.file_path, "rb") as f:
                    data = f.read()
                maintype, subtype = (attachment.mime_type or "application/octet-stream").split(
                    "/", 1
                )
                msg.add_attachment(
                    data, maintype=maintype, subtype=subtype, filename=attachment.filename
                )
            elif attachment.content_bytes:
                data = base64.b64decode(attachment.content_bytes)
                maintype, subtype = (attachment.mime_type or "application/octet-stream").split(
                    "/", 1
                )
                msg.add_attachment(
                    data, maintype=maintype, subtype=subtype, filename=attachment.filename
                )

        return msg

    def _gmail_message(self, message: _EmailMessage) -> Dict[str, Any]:
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {"raw": encoded_message}

    def _parse_gmail_message(self, msg: Dict[str, Any]) -> EmailMessage:
        payload = msg.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
        subject = headers.get("Subject", "")
        to_header = headers.get("To")
        cc_header = headers.get("Cc")
        bcc_header = headers.get("Bcc")
        from_header = headers.get("From", "")
        # Trim the raw Gmail payload to only essential, high-signal fields to
        # reduce size / token cost for downstream LLM usage.
        trimmed_payload: Dict[str, Any] = {
            "id": msg.get("id"),
            "threadId": msg.get("threadId"),
            "labelIds": msg.get("labelIds"),
            "historyId": msg.get("historyId"),
            "internalDate": msg.get("internalDate"),
            "snippet": msg.get("snippet"),
            "headers": {k: headers.get(k) for k in ("Subject", "From", "To", "Cc", "Bcc", "Date")},
        }

        return EmailMessage(
            id=msg["id"],
            account=self.account.name,
            subject=subject,
            from_=self._parse_address(from_header),
            to=self._parse_address_list(to_header),
            cc=self._parse_address_list(cc_header),
            bcc=self._parse_address_list(bcc_header),
            snippet=msg.get("snippet"),
            body_text=self._extract_plain_body(payload),
            labels=list(msg.get("labelIds", [])),
            is_read="UNREAD" not in msg.get("labelIds", []),
            thread_id=msg.get("threadId"),
            raw_provider_payload=trimmed_payload,
        )

    # ------------------------------------------------------------------
    # API methods implementing AsyncEmailProvider
    # ------------------------------------------------------------------
    async def fetch_unread(
            self, *, max_results: int = 10, include_body: bool = False
    ) -> List[EmailMessage]:
        def _inner() -> List[EmailMessage]:
            # Clip overly large requests silently to the supported maximum.
            clipped_max = min(max_results, self.MAX_FETCH_RESULTS)
            res = (
                self.service.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=clipped_max)
                .execute()
            )
            messages = []
            for item in res.get("messages", []):
                msg = (
                    self.service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=item["id"],
                        format="full" if include_body else "metadata",
                    )
                    .execute()
                )
                messages.append(self._parse_gmail_message(msg))
            return messages

        return await asyncio.to_thread(_inner)

    async def count_unread(self) -> int:
        def _inner() -> int:
            res = (
                self.service.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=1)
                .execute()
            )
            return int(res.get("resultSizeEstimate", 0))

        return await asyncio.to_thread(_inner)

    async def send_email(
            self,
            *,
            to: AddressListLike,
            subject: str,
            body_text: str,
            cc: Optional[AddressListLike] = None,
            bcc: Optional[AddressListLike] = None,
            html_body: Optional[str] = None,
            attachments: Optional[Sequence[Attachment]] = None,
    ) -> Dict[str, Any]:
        message = self._build_message(
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )

        def _inner() -> Dict[str, Any]:
            return (
                self.service.users()
                .messages()
                .send(userId="me", body=self._gmail_message(message))
                .execute()
            )

        return await asyncio.to_thread(_inner)

    async def mark_read(self, message_ids: List[str]) -> Dict[str, Any]:
        def _inner() -> Dict[str, Any]:
            return (
                self.service.users()
                .messages()
                .batchModify(
                    userId="me",
                    body={"ids": message_ids, "removeLabelIds": ["UNREAD"]},
                )
                .execute()
            )

        return await asyncio.to_thread(_inner)

    async def mark_unread(self, message_ids: List[str]) -> Dict[str, Any]:
        def _inner() -> Dict[str, Any]:
            return (
                self.service.users()
                .messages()
                .batchModify(
                    userId="me", body={"ids": message_ids, "addLabelIds": ["UNREAD"]}
                )
                .execute()
            )

        return await asyncio.to_thread(_inner)

    async def delete_message(self, message_id: str, *, permanent: bool = False) -> Dict[str, Any]:
        def _inner() -> Dict[str, Any]:
            if permanent:
                return (
                    self.service.users()
                    .messages()
                    .delete(userId="me", id=message_id)
                    .execute()
                )
            return (
                self.service.users()
                .messages()
                .trash(userId="me", id=message_id)
                .execute()
            )

        return await asyncio.to_thread(_inner)

    async def create_draft(
            self,
            *,
            to: AddressListLike,
            subject: str,
            body_text: str,
            cc: Optional[AddressListLike] = None,
            bcc: Optional[AddressListLike] = None,
            html_body: Optional[str] = None,
            attachments: Optional[Sequence[Attachment]] = None,
    ) -> Draft:
        msg = self._build_message(
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )

        def _inner() -> Draft:
            res = (
                self.service.users()
                .drafts()
                .create(userId="me", body={"message": self._gmail_message(msg)})
                .execute()
            )
            message = self._parse_gmail_message(res.get("message", {}))
            return Draft(
                id=res["id"],
                account=self.account.name,
                to=message.to,
                cc=message.cc,
                bcc=message.bcc,
                subject=message.subject,
                body_text=message.body_text,
                body_html=None,
                raw_provider_payload=res,
            )

        return await asyncio.to_thread(_inner)

    async def update_draft(
            self,
            *,
            draft_id: str,
            to: AddressListLike,
            subject: str,
            body_text: str,
            cc: Optional[AddressListLike] = None,
            bcc: Optional[AddressListLike] = None,
            html_body: Optional[str] = None,
            attachments: Optional[Sequence[Attachment]] = None,
    ) -> Draft:
        msg = self._build_message(
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )

        def _inner() -> Draft:
            res = (
                self.service.users()
                .drafts()
                .update(
                    userId="me",
                    id=draft_id,
                    body={"message": self._gmail_message(msg), "id": draft_id},
                )
                .execute()
            )
            message = self._parse_gmail_message(res.get("message", {}))
            return Draft(
                id=res["id"],
                account=self.account.name,
                to=message.to,
                cc=message.cc,
                bcc=message.bcc,
                subject=message.subject,
                body_text=message.body_text,
                body_html=None,
                raw_provider_payload=res,
            )

        return await asyncio.to_thread(_inner)

    async def send_draft(self, *, draft_id: str) -> Dict[str, Any]:
        def _inner() -> Dict[str, Any]:
            return (
                self.service.users()
                .drafts()
                .send(userId="me", body={"id": draft_id})
                .execute()
            )

        return await asyncio.to_thread(_inner)

    async def list_drafts(self, *, max_results: int = 10) -> List[Draft]:
        def _inner() -> List[Draft]:
            res = (
                self.service.users()
                .drafts()
                .list(userId="me", maxResults=max_results)
                .execute()
            )
            drafts = []
            for item in res.get("drafts", []):
                draft = (
                    self.service.users()
                    .drafts()
                    .get(userId="me", id=item["id"])
                    .execute()
                )
                message = self._parse_gmail_message(draft.get("message", {}))
                drafts.append(
                    Draft(
                        id=item["id"],
                        account=self.account.name,
                        to=message.to,
                        cc=message.cc,
                        bcc=message.bcc,
                        subject=message.subject,
                        body_text=message.body_text,
                        body_html=None,
                        raw_provider_payload=draft,
                    )
                )
            return drafts

        return await asyncio.to_thread(_inner)

    async def get_draft(self, *, draft_id: str) -> Draft:
        def _inner() -> Draft:
            res = (
                self.service.users()
                .drafts()
                .get(userId="me", id=draft_id)
                .execute()
            )
            message = self._parse_gmail_message(res.get("message", {}))
            return Draft(
                id=res["id"],
                account=self.account.name,
                to=message.to,
                cc=message.cc,
                bcc=message.bcc,
                subject=message.subject,
                body_text=message.body_text,
                body_html=None,
                raw_provider_payload=res,
            )

        return await asyncio.to_thread(_inner)

    async def delete_draft(self, *, draft_id: str) -> Dict[str, Any]:
        def _inner() -> Dict[str, Any]:
            return (
                self.service.users()
                .drafts()
                .delete(userId="me", id=draft_id)
                .execute()
            )

        return await asyncio.to_thread(_inner)

    async def get_summary(self) -> Dict[str, Any]:
        unread = await self.count_unread()
        return {"account": self.account.name, "unread": unread}
