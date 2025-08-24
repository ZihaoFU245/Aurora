from typing import List, Any

from .config import Config
from .tools import (
    add_account,
    list_email_accounts,
    email_fetch_unread,
    email_send,
    email_mark_read,
    email_mark_unread,
    email_delete_message,
    email_count_unread,
    email_create_draft,
    email_update_draft,
    email_send_draft,
    email_list_drafts,
    email_get_draft,
    email_delete_draft,
)

config = Config()

__all__ = [
    "add_account",
    "list_email_accounts",
    "email_fetch_unread",
    "email_send",
    "email_mark_read",
    "email_mark_unread",
    "email_delete_message",
    "email_count_unread",
    "email_create_draft",
    "email_update_draft",
    "email_send_draft",
    "email_list_drafts",
    "email_get_draft",
    "email_delete_draft",
    "config",
    "getAll"
]


def getAll() -> List[Any]:
    return [
        add_account,
        list_email_accounts,
        email_fetch_unread,
        email_send,
        email_mark_read,
        email_mark_unread,
        email_delete_message,
        email_count_unread,
        email_create_draft,
        email_update_draft,
        email_send_draft,
        email_list_drafts,
        email_get_draft,
        email_delete_draft,
    ]
