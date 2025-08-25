from __future__ import annotations

from typing import Any, Dict, List, Sequence, Optional, Type, Mapping
import json
import os

from .config import Config

from .abc import AsyncEmailProvider, AddressListLike
from .models import AccountInfo, Attachment, Draft, EmailMessage


class AllEmails:
    """A multiaccount email manager with lightweight persistence.

    Persistence:
      - Accounts are stored (name, provider, email) in JSON at
        ``Config.EMAIL_ACCOUNTS_PATH`` or a default ``email_accounts.json``.
      - On initialization previously stored accounts are loaded and their
        providers instantiated using the supplied ``providers`` registry
        (mapping provider key -> provider class).
      - Registering or unregistering an account re-writes the JSON file.
    """

    def __init__(self, *, providers: Optional[Mapping[str, Type[AsyncEmailProvider]]] = None) -> None:
        self._providers: Dict[str, AsyncEmailProvider] = {}
        # Mapping of provider key -> provider class (injected to avoid circular imports)
        self._provider_classes: Dict[str, Type[AsyncEmailProvider]] = {
            **(providers or {})
        }
        # Determine accounts file path: use configured path, else place in this package directory.
        if Config.EMAIL_ACCOUNTS_PATH:
            self._accounts_file = os.path.join(Config.EMAIL_ACCOUNTS_PATH, "email_accounts.json")
        else:
            self._accounts_file = os.path.join(os.path.dirname(__file__), "email_accounts.json")
        # Create an empty accounts file if none exists so users can verify path
        if not os.path.exists(self._accounts_file):
            try:
                directory = os.path.dirname(self._accounts_file)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                with open(self._accounts_file, "w", encoding="utf-8") as f:
                    json.dump([], f)
            except Exception as e:  # noqa: BLE001
                print(f"[EmailTools] Could not initialize accounts file {self._accounts_file}: {e}")
        if os.getenv("EMAIL_TOOLS_DEBUG"):
            print(f"[EmailTools] Using accounts file: {self._accounts_file}")
        self._load_persisted_accounts()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _ensure_accounts_dir(self) -> None:
        directory = os.path.dirname(self._accounts_file)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def _persist_accounts(self) -> None:
        if not self._accounts_file:
            return
        try:
            self._ensure_accounts_dir()
            data = [
                {"name": p.account.name, "provider": p.account.provider, "email": p.account.email}
                for p in self._providers.values()
            ]
            with open(self._accounts_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            # Lightweight diagnostic so users can see persistence working (can be removed or gated by env flag later)
            if os.getenv("EMAIL_TOOLS_DEBUG"):
                print(f"[EmailTools] Persisted {len(data)} account(s) to {self._accounts_file}")
        except Exception as e:  # noqa: BLE001
            print(f"[EmailTools] Failed to persist accounts: {e}")

    def _load_persisted_accounts(self) -> None:
        path = self._accounts_file
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f) or []
        except Exception as e:  # noqa: BLE001
            print(f"[EmailTools] Failed to load accounts file {path}: {e}")
            return
        if not isinstance(entries, list):
            print(f"[EmailTools] Accounts file {path} invalid format; skipping load")
            return
        for entry in entries:
            try:
                name = entry.get("name")
                provider_key = (entry.get("provider") or "").lower()
                email = entry.get("email")
                if not (name and provider_key and email):
                    continue
                provider_cls = self._provider_classes.get(provider_key)
                if not provider_cls:
                    print(f"[EmailTools] Unknown provider '{provider_key}' in file; skipping")
                    continue
                acc = AccountInfo(name=name, provider=provider_key, email=email)
                provider_instance = provider_cls(acc, {})  # type: ignore[arg-type]
                # Avoid persisting again while loading
                self.register(provider_instance, persist=False)
            except Exception as e:  # noqa: BLE001
                print(f"[EmailTools] Failed to restore account entry {entry}: {e}")

    # ------------------------------------------------------------------
    # Account management
    # ------------------------------------------------------------------
    def register(self, provider: AsyncEmailProvider, *, persist: bool = True) -> None:
        """Register a provider instance for its account name and persist."""

        self._providers[provider.account.name] = provider
        if persist:
            self._persist_accounts()

    def unregister(self, account: str) -> None:
        """Remove a provider from management if present."""
        self._providers.pop(account, None)
        self._persist_accounts()

    def get_accounts(self) -> List[AccountInfo]:
        """Return metadata for all managed accounts."""

        return [p.account for p in self._providers.values()]

    def _get(self, account: str) -> AsyncEmailProvider:
        # Direct name lookup first
        if account in self._providers:
            return self._providers[account]
        # Fallback: lookup by email address (case-insensitive)
        lowered = account.lower()
        for prov in self._providers.values():
            if prov.account.email.lower() == lowered:
                return prov
        available = [f"{p.account.name} ({p.account.email})" for p in self._providers.values()] or ["<none>"]
        raise KeyError(
            f"Account '{account}' is not registered. Available: {', '.join(available)}"
        )

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
