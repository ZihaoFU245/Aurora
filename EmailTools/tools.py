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
from typing import Optional, Sequence, Any, Dict, Iterable, List, Union
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor

from langchain_core.tools import tool

from .AllEmails import AllEmails
from .Providers.GmailClient import GmailClient
from .abc import AddressListLike
from .models import AccountInfo, Attachment, Draft

# Mapping of supported provider identifiers to their client classes
PROVIDERS = {
    "gmail": GmailClient,
}

# A single manager instance used by all tools (persistence handled inside)
email_manager = AllEmails(providers=PROVIDERS)

# ---- helpers ----
_EXECUTOR = ThreadPoolExecutor(max_workers=1)

def _run(coro):
    """
    Run an async coroutine from a sync context.
    - If there's no running event loop, use asyncio.run(coro).
    - If already in an event loop, run it in a private loop inside a worker thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    def _runner():
        return asyncio.run(coro)

    fut = _EXECUTOR.submit(_runner)
    return fut.result()


def _coerce_ids(value: Any) -> list[str]:
    """
    Accepts a single id string, an iterable of ids, or an iterable of dicts with 'id'.
    Returns a list[str] suitable for provider.batchModify.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        out: list[str] = []
        for v in value:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and "id" in v:
                out.append(str(v["id"]))
            else:
                out.append(str(v))
        return out
    return [str(value)]


def _ok(data: Any = None, **meta: Any) -> Dict[str, Any]:  # Helper for uniform success
    return {"success": True, "data": data, **({"meta": meta} if meta else {})}


def _err(error: str, **meta: Any) -> Dict[str, Any]:  # Helper for uniform failure
    return {"success": False, "error": error, **({"meta": meta} if meta else {})}


def _resolve_account_name(account: Optional[str]) -> str:
    """
    If the caller didn't pass an account, use the only registered one.
    If there are 0 or >1 accounts, raise ValueError with a helpful message.
    """
    # Accept a full account dict (as returned by list_email_accounts) for robustness.
    if isinstance(account, dict):  # type: ignore[redundant-expr]
        # Prefer provided name; fall back to email if name missing.
        name = account.get("name") or account.get("email")
        if name:
            return name
    if account:
        return account
    accounts = email_manager.get_accounts()
    if len(accounts) == 1:
        return accounts[0].name
    available = [f"{a.name} ({a.email})" for a in accounts] or ["<none>"]
    raise ValueError(
        "account is required; none was provided and auto-selection is ambiguous. "
        f"Available: {', '.join(available)}"
    )


def _coerce_attachments(raw: Optional[Sequence[Any]]) -> Optional[List[Attachment]]:
    """Normalize a variety of user-friendly attachment specs into Attachment objects.

    Accepted forms (mixed allowed):
      - Attachment dataclass instances (passed through)
      - String paths: "reports/summary.pdf"
      - Dicts with keys:
          {"path": "..."} or {"file_path": "..."}
          Optional: filename, mime_type, content_bytes
      - Dicts with already-correct keys for Attachment

    If a dict supplies only a path/file_path and no filename, the basename is used.
    Missing files raise a ValueError listing all missing paths (fail-fast before API call).
    """
    if raw is None:
        return None
    out: List[Attachment] = []
    missing: List[str] = []
    for item in raw:
        if isinstance(item, Attachment):
            # Ensure filename if possible from file_path
            if not item.filename and item.file_path:
                item.filename = os.path.basename(item.file_path)
            out.append(item)
            continue
        if isinstance(item, str):
            path = item
            if not os.path.exists(path):
                missing.append(path)
            out.append(Attachment(filename=os.path.basename(path), file_path=path))
            continue
        if isinstance(item, dict):
            # Support legacy key 'path'
            path = item.get("file_path") or item.get("path")
            filename = item.get("filename")
            mime_type = item.get("mime_type")
            content_b64 = item.get("content_bytes") or item.get("content_b64")
            if path:
                if not filename:
                    filename = os.path.basename(path)
                if not os.path.exists(path):
                    missing.append(path)
                out.append(
                    Attachment(
                        filename=filename,
                        file_path=path,
                        mime_type=mime_type,
                        content_bytes=content_b64,
                    )
                )
            else:
                # Inlined content (must supply filename + content)
                if not (filename and content_b64):
                    raise ValueError(
                        "Inline attachment dict must include filename and content_bytes/content_b64"
                    )
                out.append(
                    Attachment(
                        filename=filename,
                        mime_type=mime_type,
                        content_bytes=content_b64,
                    )
                )
            continue
        raise TypeError(f"Unsupported attachment spec: {item!r}")
    if missing:
        raise ValueError(f"attachment file(s) not found: {', '.join(missing)}")
    return out


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
def email_fetch_unread(
    account: Optional[str] = None, max_results: int = 10, include_body: bool = False
) -> dict:
    """Fetch unread messages for the given account."""
    try:
        acct = _resolve_account_name(account)
        msgs = _run(email_manager.fetch_unread(
            acct, max_results=max_results, include_body=include_body
        ))
        return _ok([asdict(m) for m in msgs], count=len(msgs), account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"unread fetch failed: {e}")


@tool("email_send")
def email_send(
    account: Optional[Union[str, Dict[str, Any]]] = None,
    *,
    to: AddressListLike,
    subject: str,
    body_text: str,
    cc: Optional[AddressListLike] = None,
    bcc: Optional[AddressListLike] = None,
    html_body: Optional[str] = None,
    attachments: Optional[Sequence[Any]] = None,
) -> dict:
    """Send an email using the specified account.

    Attachment flexibility: accepts list of
      - paths (str)
      - dicts with path/file_path (+ optional filename, mime_type)
      - dicts with filename + content_bytes (base64)
      - Attachment objects
    """
    try:
        acct = _resolve_account_name(account)  # type: ignore[arg-type]
        norm_attachments = _coerce_attachments(attachments)
        res = _run(
            email_manager.send_email(
                acct,
                to=to,
                subject=subject,
                body_text=body_text,
                cc=cc,
                bcc=bcc,
                html_body=html_body,
                attachments=norm_attachments,
            )
        )
        data = {
            "status": "sent",
            "message_id": res.get("id"),
            "thread_id": res.get("threadId"),
        }
        return _ok(data, account=acct, raw=res)
    except Exception as e:  # noqa: BLE001
        return _err(f"send failed: {e}")


@tool("email_mark_read")
def email_mark_read(account: Optional[str] = None, message_ids: Sequence[str] | str = ()) -> dict:
    """Mark the given message ids as read for an account."""
    try:
        acct = _resolve_account_name(account)
        ids = _coerce_ids(message_ids)
        res = _run(email_manager.mark_read(acct, ids))
        return _ok({"marked_read": ids, "provider_response": res}, account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"mark read failed: {e}")


@tool("email_mark_unread")
def email_mark_unread(account: Optional[str] = None, message_ids: Sequence[str] | str = ()) -> dict:
    """Mark the given message ids as unread for an account."""
    try:
        acct = _resolve_account_name(account)
        ids = _coerce_ids(message_ids)
        res = _run(email_manager.mark_unread(acct, ids))
        return _ok({"marked_unread": ids, "provider_response": res}, account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"mark unread failed: {e}")


@tool("email_delete_message")
def email_delete_message(
    account: Optional[str] = None, message_id: str = "", *, permanent: bool = False
) -> dict:
    """Delete a message; use permanent=True to skip trash."""
    try:
        acct = _resolve_account_name(account)
        res = _run(email_manager.delete_message(acct, message_id, permanent=permanent))
        return _ok({"deleted": message_id, "permanent": permanent, "provider_response": res}, account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"delete failed: {e}")


@tool("email_count_unread")
def email_count_unread(account: Optional[str] = None) -> dict:
    """Return the number of unread messages for an account."""
    try:
        acct = _resolve_account_name(account)
        count = _run(email_manager.count_unread(acct))
        return _ok({"unread": count}, account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"count failed: {e}")


@tool("email_create_draft")
def email_create_draft(
    account: Optional[Union[str, Dict[str, Any]]] = None,
    *,
    to: AddressListLike,
    subject: str,
    body_text: str,
    cc: Optional[AddressListLike] = None,
    bcc: Optional[AddressListLike] = None,
    html_body: Optional[str] = None,
    attachments: Optional[Sequence[Any]] = None,
) -> dict:
    """Create a draft email and return its metadata (supports flexible attachment specs)."""
    try:
        acct = _resolve_account_name(account)  # type: ignore[arg-type]
        norm_attachments = _coerce_attachments(attachments)
        draft: Draft = _run(
            email_manager.create_draft(
                acct,
                to=to,
                subject=subject,
                body_text=body_text,
                cc=cc,
                bcc=bcc,
                html_body=html_body,
                attachments=norm_attachments,
            )
        )
        return _ok(asdict(draft), account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"create draft failed: {e}")


@tool("email_update_draft")
def email_update_draft(
    account: Optional[Union[str, Dict[str, Any]]] = None,
    *,
    draft_id: str,
    to: AddressListLike,
    subject: str,
    body_text: str,
    cc: Optional[AddressListLike] = None,
    bcc: Optional[AddressListLike] = None,
    html_body: Optional[str] = None,
    attachments: Optional[Sequence[Any]] = None,
) -> dict:
    """Update an existing draft (supports flexible attachment specs)."""
    try:
        acct = _resolve_account_name(account)  # type: ignore[arg-type]
        norm_attachments = _coerce_attachments(attachments)
        draft: Draft = _run(
            email_manager.update_draft(
                acct,
                draft_id=draft_id,
                to=to,
                subject=subject,
                body_text=body_text,
                cc=cc,
                bcc=bcc,
                html_body=html_body,
                attachments=norm_attachments,
            )
        )
        return _ok(asdict(draft), account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"update draft failed: {e}")


@tool("email_send_draft")
def email_send_draft(account: Optional[str] = None, *, draft_id: str) -> dict:
    """Send a previously created draft."""
    try:
        acct = _resolve_account_name(account)
        res = _run(email_manager.send_draft(acct, draft_id=draft_id))
        data = {
            "status": "sent_draft",
            "draft_id": draft_id,
            "message_id": res.get("id"),
            "thread_id": res.get("threadId"),
        }
        return _ok(data, account=acct, raw=res)
    except Exception as e:  # noqa: BLE001
        return _err(f"send draft failed: {e}")


@tool("email_list_drafts")
def email_list_drafts(account: Optional[str] = None, max_results: int = 10) -> dict:
    """List drafts for an account."""
    try:
        acct = _resolve_account_name(account)
        drafts = _run(email_manager.list_drafts(acct, max_results=max_results))
        return _ok([asdict(d) for d in drafts], count=len(drafts), account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"list drafts failed: {e}")


@tool("email_get_draft")
def email_get_draft(account: Optional[str] = None, *, draft_id: str) -> dict:
    """Retrieve a single draft by id."""
    try:
        acct = _resolve_account_name(account)
        draft = _run(email_manager.get_draft(acct, draft_id=draft_id))
        return _ok(asdict(draft), account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"get draft failed: {e}")


@tool("email_delete_draft")
def email_delete_draft(account: Optional[str] = None, *, draft_id: str) -> dict:
    """Delete a draft."""
    try:
        acct = _resolve_account_name(account)
        res = _run(email_manager.delete_draft(acct, draft_id=draft_id))
        return _ok({"deleted_draft": draft_id, "provider_response": res}, account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"delete draft failed: {e}")


@tool("email_health")
def email_health(account: Optional[str] = None) -> dict:
    """Basic health check: returns unread count to validate connectivity."""
    try:
        acct = _resolve_account_name(account)
        count = _run(email_manager.count_unread(acct))
        return _ok({"unread": count}, account=acct)
    except Exception as e:  # noqa: BLE001
        return _err(f"health check failed: {e}")
