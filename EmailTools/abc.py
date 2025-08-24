from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple, Optional, Sequence, Union

from .models import EmailAddress, EmailMessage, Draft, Attachment, AccountInfo, ProviderCapabilities

AddressLike = Union[str, EmailAddress]
AddressListLike = Union[str, Sequence[AddressLike]]


class AsyncEmailProvider(ABC):
    """
    Abstract base for provider implementations (Gmail, Outlook, IMAP...).

    Each provider gets its AccountInfo (public metadata) and a secrets dict
    (tokens, client ids, refresh tokens, etc.).

    Each class is one email account.
    Token and authentication is left to each class.
    """

    def __init__(self, account: AccountInfo, secrets: Dict[str, str]):
        self.account = account
        self.secrets = secrets

    # -------------------- Reading --------------------
    @abstractmethod
    async def fetch_unread(self, *, max_results: int = 10, include_body: bool = False) -> List[EmailMessage]:
        """Return a list of unread messages for this account."""

    @abstractmethod
    async def count_unread(self) -> int:
        """Return unread count for this account."""

    # -------------------- Sending --------------------
    @abstractmethod
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
        """Send a message and return provider result (IDs, status, etc.)."""

    # -------------------- Message state --------------------
    @abstractmethod
    async def mark_read(self, message_ids: List[str]) -> Dict[str, Any]: ...

    @abstractmethod
    async def mark_unread(self, message_ids: List[str]) -> Dict[str, Any]: ...

    @abstractmethod
    async def delete_message(self, message_id: str, *, permanent: bool = False) -> Dict[str, Any]: ...

    # -------------------- Drafts --------------------
    @abstractmethod
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
    ) -> Draft: ...

    @abstractmethod
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
    ) -> Draft: ...

    @abstractmethod
    async def send_draft(self, *, draft_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    async def list_drafts(self, *, max_results: int = 10) -> List[Draft]: ...

    @abstractmethod
    async def get_draft(self, *, draft_id: str) -> Draft: ...

    @abstractmethod
    async def delete_draft(self, *, draft_id: str) -> Dict[str, Any]: ...

    # -------------------- Info --------------------
    @abstractmethod
    async def get_summary(self) -> Dict[str, Any]:
        """Return quick account/provider summary (for dashboards)."""
