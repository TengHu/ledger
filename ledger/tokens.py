"""Plaid access token storage via OS keyring.

Tokens are long-lived OAuth credentials that grant read access to your
bank accounts. They live in the macOS keychain (or equivalent on Linux/
Windows) via the `keyring` library — never in plaintext files, never in
the SQLite DB, never in the repo.

Each token is keyed by item_id (Plaid's per-connection identifier). The
items table in the DB tracks which item_ids exist; the actual token
material is in keyring.
"""

from __future__ import annotations

import keyring

_SERVICE = "ledger.plaid"


def save_token(item_id: str, access_token: str) -> None:
    """Persist an access token under item_id."""
    keyring.set_password(_SERVICE, item_id, access_token)


def get_token(item_id: str) -> str | None:
    """Look up an access token by item_id. Returns None if not stored."""
    return keyring.get_password(_SERVICE, item_id)


def delete_token(item_id: str) -> None:
    """Remove a stored token. Idempotent — silent if not present."""
    try:
        keyring.delete_password(_SERVICE, item_id)
    except keyring.errors.PasswordDeleteError:
        pass
