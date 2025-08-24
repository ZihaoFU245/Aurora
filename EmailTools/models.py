from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class EmailAddress:
    """A single email address with display name"""
    email: str
    name: Optional[str] = None


@dataclass
class Attachment:
    """
    Represents an attachment you can send/receive.
    For sending, set either file_path or (content_bytes + mime_type + filename).
    Providers may return provider_id for fetched messages.
    """
    filename: str
    mime_type: Optional[str] = None
    file_path: Optional[str] = None
    content_bytes: Optional[str] = None
    provider_id: Optional[str] = None


@dataclass
class ProviderCapabilities:
    """Flags describing what a provider supports."""
    drafts: bool = True
    labels: bool = True
    threads: bool = True
    attachments: bool = True


@dataclass
class AccountInfo:
    """Static metadata for an account (non-secret)."""
    name: str  # e.g. "personal", "work"
    provider: str  # e.g. "gmail", "outlook", "imap"
    email: str
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)


@dataclass
class EmailMessage:
    id: str
    account: str
    subject: str
    from_: EmailAddress
    to: List[EmailAddress] = field(default_factory=list)
    cc: List[EmailAddress] = field(default_factory=list)
    bcc: List[EmailAddress] = field(default_factory=list)
    snippet: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    is_read: bool = False
    thread_id: Optional[str] = None
    date: Optional[datetime] = None
    attachments: List[Attachment] = field(default_factory=list)
    raw_provider_payload: Optional[Dict[str, Any]] = None


@dataclass
class Draft:
    id: str
    account: str
    to: List[EmailAddress] = field(default_factory=list)
    cc: List[EmailAddress] = field(default_factory=list)
    bcc: List[EmailAddress] = field(default_factory=list)
    subject: str = ""
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)
    raw_provider_payload: Optional[Dict[str, Any]] = None
