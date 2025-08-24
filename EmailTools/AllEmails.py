from __future__ import annotations

from typing import Any, Dict, List, Sequence, Optional

from .abc import AsyncEmailProvider, AddressListLike
from .models import AccountInfo, Attachment, Draft, EmailMessage


class AllEmails:
    """A multiaccount email manager.

    This class acts as a thin wrapper around multiple
    :class:`~EmailTools.abc.AsyncEmailProvider` instances. It mirrors the
    provider API but requires an ``account`` parameter to identify which
    provider should handle the call.
    """

    def __init__(self) -> None:
        self._providers: Dict[str, AsyncEmailProvider] = {}

    # ------------------------------------------------------------------
    # Account management
    # ------------------------------------------------------------------
    def register(self, provider: AsyncEmailProvider) -> None:
        """Register a provider instance for its account name."""

        self._providers[provider.account.name] = provider

    def unregister(self, account: str) -> None:
        """Remove a provider from management if present."""

        self._providers.pop(account, None)

    def get_accounts(self) -> List[AccountInfo]:
        """Return metadata for all managed accounts."""

        return [p.account for p in self._providers.values()]

    def _get(self, account: str) -> AsyncEmailProvider:
        if account not in self._providers:
            raise KeyError(f"Account '{account}' is not registered")
        return self._providers[account]

    # ------------------------------------------------------------------
    # Methods mirroring AsyncEmailProvider with an extra `account` param
    # ------------------------------------------------------------------
    async def fetch_unread(
            self, account: str, *, max_results: int = 10, include_body: bool = False
    ) -> List[EmailMessage]:
        provider = self._get(account)
        return await provider.fetch_unread(
            max_results=max_results, include_body=include_body
        )

    async def count_unread(self, account: str) -> int:
        provider = self._get(account)
        return await provider.count_unread()

    async def send_email(
            self,
            account: str,
            *,
            to: AddressListLike,
            subject: str,
            body_text: str,
            cc: Optional[AddressListLike] = None,
            bcc: Optional[AddressListLike] = None,
            html_body: Optional[str] = None,
            attachments: Optional[Sequence[Attachment]] = None,
    ) -> Dict[str, Any]:
        provider = self._get(account)
        return await provider.send_email(
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )

    async def mark_read(self, account: str, message_ids: List[str]) -> Dict[str, Any]:
        provider = self._get(account)
        return await provider.mark_read(message_ids)

    async def mark_unread(self, account: str, message_ids: List[str]) -> Dict[str, Any]:
        provider = self._get(account)
        return await provider.mark_unread(message_ids)

    async def delete_message(
            self, account: str, message_id: str, *, permanent: bool = False
    ) -> Dict[str, Any]:
        provider = self._get(account)
        return await provider.delete_message(message_id, permanent=permanent)

    async def create_draft(
            self,
            account: str,
            *,
            to: AddressListLike,
            subject: str,
            body_text: str,
            cc: Optional[AddressListLike] = None,
            bcc: Optional[AddressListLike] = None,
            html_body: Optional[str] = None,
            attachments: Optional[Sequence[Attachment]] = None,
    ) -> Draft:
        provider = self._get(account)
        return await provider.create_draft(
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )

    async def update_draft(
            self,
            account: str,
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
        provider = self._get(account)
        return await provider.update_draft(
            draft_id=draft_id,
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )

    async def send_draft(self, account: str, *, draft_id: str) -> Dict[str, Any]:
        provider = self._get(account)
        return await provider.send_draft(draft_id=draft_id)

    async def list_drafts(
            self, account: str, *, max_results: int = 10
    ) -> List[Draft]:
        provider = self._get(account)
        return await provider.list_drafts(max_results=max_results)

    async def get_draft(self, account: str, *, draft_id: str) -> Draft:
        provider = self._get(account)
        return await provider.get_draft(draft_id=draft_id)

    async def delete_draft(self, account: str, *, draft_id: str) -> Dict[str, Any]:
        provider = self._get(account)
        return await provider.delete_draft(draft_id=draft_id)

    async def get_summary(self, account: str) -> Dict[str, Any]:
        provider = self._get(account)
        return await provider.get_summary()
