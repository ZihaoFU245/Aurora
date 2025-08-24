"""Email related tools exposed for the agent framework.

Unified return contract:
Each tool returns a dict with keys:
    - success: bool
    - data: payload (any) when success True
    - error: message (str) when success False
    - meta: optional extra info

This avoids opaque exceptions (e.g. "Result is not set") leaking to the
agent layer. Internal exceptions are caught at the tool boundary and
transformed into structured failures while preserving message clarity.
"""

from dataclasses import asdict
from typing import Optional, Sequence, Any, Dict
from datetime import datetime

from langchain_core.tools import tool

from .AllEmails import AllEmails
from .Providers.GmailClient import GmailClient
from .abc import AddressListLike
from .models import AccountInfo, Attachment, Draft, EmailMessage

# Mapping of supported provider identifiers to their client classes
PROVIDERS = {
    "gmail": GmailClient,
}

# A single manager instance used by all tools (persistence handled inside)
email_manager = AllEmails(providers=PROVIDERS)


def _ok(data: Any = None, **meta: Any) -> Dict[str, Any]:  # Helper for uniform success
    return {"success": True, "data": data, **({"meta": meta} if meta else {})}


def _err(error: str, **meta: Any) -> Dict[str, Any]:  # Helper for uniform failure
    return {"success": False, "error": error, **({"meta": meta} if meta else {})}


@tool("add_account")
def add_account(provider: str, name: str, email: str) -> dict:
    """Add a new email account and trigger auth if needed."""

    provider_key = provider.lower()
    provider_cls = PROVIDERS.get(provider_key)
    if not provider_cls:
        return _err(f"provider '{provider}' is not supported")
    account = AccountInfo(name=name, provider=provider_key, email=email)
    try:
        provider_instance = provider_cls(account, {})  # type: ignore[arg-type]
        email_manager.register(provider_instance)
        return _ok({"account": asdict(account)})
    except Exception as e:  # noqa: BLE001
        return _err(f"failed to register {name}: {e}")


@tool("list_email_accounts")
def list_email_accounts() -> dict:
    """List all registered email accounts."""
    try:
        return _ok([asdict(acc) for acc in email_manager.get_accounts()])
    except Exception as e:  # noqa: BLE001
        return _err(f"failed to list accounts: {e}")


@tool("email_fetch_unread")
async def email_fetch_unread(
    account: str, max_results: int = 10, include_body: bool = False
) -> dict:
    """Fetch unread messages for the given account."""

    def _serialize_msg(msg: EmailMessage) -> Dict[str, Any]:
        data = asdict(msg)
        dt = data.get("date")
        if isinstance(dt, datetime):
            data["date"] = dt.isoformat()
        return data

    try:
        msgs = await email_manager.fetch_unread(
            account, max_results=max_results, include_body=include_body
        )
        return _ok([_serialize_msg(m) for m in msgs], count=len(msgs))
    except Exception as e:  # noqa: BLE001
        return _err(f"unread fetch failed: {e}")


@tool("email_send")
async def email_send(
    account: str,
    *,
    to: AddressListLike,
    subject: str,
    body_text: str,
    cc: Optional[AddressListLike] = None,
    bcc: Optional[AddressListLike] = None,
    html_body: Optional[str] = None,
    attachments: Optional[Sequence[Attachment]] = None,
) -> dict:
    """Send an email using the specified account."""
    try:
        res = await email_manager.send_email(
            account,
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )
        return _ok(res)
    except Exception as e:  # noqa: BLE001
        return _err(f"send failed: {e}")


@tool("email_mark_read")
async def email_mark_read(account: str, message_ids: Sequence[str]) -> dict:
    """Mark the given message ids as read for an account."""
    try:
        return _ok(await email_manager.mark_read(account, list(message_ids)))
    except Exception as e:  # noqa: BLE001
        return _err(f"mark read failed: {e}")


@tool("email_mark_unread")
async def email_mark_unread(account: str, message_ids: Sequence[str]) -> dict:
    """Mark the given message ids as unread for an account."""
    try:
        return _ok(await email_manager.mark_unread(account, list(message_ids)))
    except Exception as e:  # noqa: BLE001
        return _err(f"mark unread failed: {e}")


@tool("email_delete_message")
async def email_delete_message(
    account: str, message_id: str, *, permanent: bool = False
) -> dict:
    """Delete a message; use permanent=True to skip trash."""
    try:
        return _ok(await email_manager.delete_message(account, message_id, permanent=permanent))
    except Exception as e:  # noqa: BLE001
        return _err(f"delete failed: {e}")


@tool("email_count_unread")
async def email_count_unread(account: str) -> dict:
    """Return the number of unread messages for an account."""
    try:
        count = await email_manager.count_unread(account)
        return _ok({"unread": count})
    except Exception as e:  # noqa: BLE001
        return _err(f"count failed: {e}")


@tool("email_create_draft")
async def email_create_draft(
    account: str,
    *,
    to: AddressListLike,
    subject: str,
    body_text: str,
    cc: Optional[AddressListLike] = None,
    bcc: Optional[AddressListLike] = None,
    html_body: Optional[str] = None,
    attachments: Optional[Sequence[Attachment]] = None,
) -> dict:
    """Create a draft email and return its metadata."""
    try:
        draft: Draft = await email_manager.create_draft(
            account,
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )
        return _ok(asdict(draft))
    except Exception as e:  # noqa: BLE001
        return _err(f"create draft failed: {e}")


@tool("email_update_draft")
async def email_update_draft(
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
) -> dict:
    """Update an existing draft."""
    try:
        draft: Draft = await email_manager.update_draft(
            account,
            draft_id=draft_id,
            to=to,
            subject=subject,
            body_text=body_text,
            cc=cc,
            bcc=bcc,
            html_body=html_body,
            attachments=attachments,
        )
        return _ok(asdict(draft))
    except Exception as e:  # noqa: BLE001
        return _err(f"update draft failed: {e}")


@tool("email_send_draft")
async def email_send_draft(account: str, *, draft_id: str) -> dict:
    """Send a previously created draft."""
    try:
        return _ok(await email_manager.send_draft(account, draft_id=draft_id))
    except Exception as e:  # noqa: BLE001
        return _err(f"send draft failed: {e}")


@tool("email_list_drafts")
async def email_list_drafts(account: str, max_results: int = 10) -> dict:
    """List drafts for an account."""
    try:
        drafts = await email_manager.list_drafts(account, max_results=max_results)
        return _ok([asdict(d) for d in drafts], count=len(drafts))
    except Exception as e:  # noqa: BLE001
        return _err(f"list drafts failed: {e}")


@tool("email_get_draft")
async def email_get_draft(account: str, *, draft_id: str) -> dict:
    """Retrieve a single draft by id."""
    try:
        draft = await email_manager.get_draft(account, draft_id=draft_id)
        return _ok(asdict(draft))
    except Exception as e:  # noqa: BLE001
        return _err(f"get draft failed: {e}")


@tool("email_delete_draft")
async def email_delete_draft(account: str, *, draft_id: str) -> dict:
    """Delete a draft."""
    try:
        return _ok(await email_manager.delete_draft(account, draft_id=draft_id))
    except Exception as e:  # noqa: BLE001
        return _err(f"delete draft failed: {e}")


@tool("email_health")
async def email_health(account: str) -> dict:
    """Basic health check: returns unread count to validate connectivity."""
    try:
        count = await email_manager.count_unread(account)
        return _ok({"unread": count})
    except Exception as e:  # noqa: BLE001
        return _err(f"health check failed: {e}")
