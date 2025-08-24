"""Email related tools exposed for the agent framework."""

from dataclasses import asdict
from typing import Optional, Sequence

from langchain_core.tools import tool

from .AllEmails import AllEmails
from .Providers.GmailClient import GmailClient
from .abc import AddressListLike
from .models import AccountInfo, Attachment, Draft

# A single manager instance used by all tools
email_manager = AllEmails()

# Mapping of supported provider identifiers to their client classes
PROVIDERS = {
    "gmail": GmailClient,
}


@tool("add_account")
def add_account(provider: str, name: str, email: str) -> str:
    """Add a new email account for the specified provider and trigger auth if needed."""

    provider_key = provider.lower()
    provider_cls = PROVIDERS.get(provider_key)
    if not provider_cls:
        return f"provider '{provider}' is not supported"

    account = AccountInfo(name=name, provider=provider_key, email=email)
    try:
        # Instantiating the provider triggers authentication (e.g., Gmail OAuth)
        provider_instance = provider_cls(account, {})
        email_manager.register(provider_instance)
    except Exception as e:
        return f"failed to register {name}: {e}"
    return f"registered {name}"


@tool("list_email_accounts")
def list_email_accounts() -> list:
    """Return a list of registered email accounts."""

    return [asdict(acc) for acc in email_manager.get_accounts()]


@tool("email_fetch_unread")
async def email_fetch_unread(
    account: str, max_results: int = 10, include_body: bool = False
) -> list:
    """Fetch unread messages for the given account."""

    msgs = await email_manager.fetch_unread(
        account, max_results=max_results, include_body=include_body
    )
    return [asdict(m) for m in msgs]


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

    return await email_manager.send_email(
        account,
        to=to,
        subject=subject,
        body_text=body_text,
        cc=cc,
        bcc=bcc,
        html_body=html_body,
        attachments=attachments,
    )


@tool("email_mark_read")
async def email_mark_read(account: str, message_ids: Sequence[str]) -> dict:
    """Mark the given message ids as read for an account."""

    return await email_manager.mark_read(account, list(message_ids))


@tool("email_mark_unread")
async def email_mark_unread(account: str, message_ids: Sequence[str]) -> dict:
    """Mark the given message ids as unread for an account."""

    return await email_manager.mark_unread(account, list(message_ids))


@tool("email_delete_message")
async def email_delete_message(
    account: str, message_id: str, *, permanent: bool = False
) -> dict:
    """Delete a message; use ``permanent=True`` to skip trash."""

    return await email_manager.delete_message(account, message_id, permanent=permanent)


@tool("email_count_unread")
async def email_count_unread(account: str) -> int:
    """Return the number of unread messages for an account."""

    return await email_manager.count_unread(account)


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
    return asdict(draft)


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
    return asdict(draft)


@tool("email_send_draft")
async def email_send_draft(account: str, *, draft_id: str) -> dict:
    """Send a previously created draft."""

    return await email_manager.send_draft(account, draft_id=draft_id)


@tool("email_list_drafts")
async def email_list_drafts(account: str, max_results: int = 10) -> list:
    """List drafts for an account."""

    drafts = await email_manager.list_drafts(account, max_results=max_results)
    return [asdict(d) for d in drafts]


@tool("email_get_draft")
async def email_get_draft(account: str, *, draft_id: str) -> dict:
    """Retrieve a single draft by id."""

    draft = await email_manager.get_draft(account, draft_id=draft_id)
    return asdict(draft)


@tool("email_delete_draft")
async def email_delete_draft(account: str, *, draft_id: str) -> dict:
    """Delete a draft."""

    return await email_manager.delete_draft(account, draft_id=draft_id)
