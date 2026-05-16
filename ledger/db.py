"""SQLite schema + connection helpers.

The database is the single source of truth for what ledger knows. Plaid
calls write into it; MCP tools read from it. Schema is denormalized for
ease of querying from MCP — every row carries enough context that no
joins are needed for typical agent queries.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id        TEXT PRIMARY KEY,        -- Plaid item identifier
    institution    TEXT NOT NULL,           -- "Wells Fargo", "Vanguard", etc.
    created_at     TEXT NOT NULL,
    last_refresh   TEXT,                    -- ISO 8601 UTC
    status         TEXT                     -- "active" | "needs_reauth" | "removed"
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id     TEXT PRIMARY KEY,
    item_id        TEXT NOT NULL,
    institution    TEXT NOT NULL,
    name           TEXT NOT NULL,
    official_name  TEXT,
    type           TEXT NOT NULL,           -- "depository" | "investment" | "credit" | "loan"
    subtype        TEXT,                    -- "checking" | "savings" | "401k" | "brokerage"
    mask           TEXT,                    -- last 4 of account number
    balance_current      REAL,
    balance_available    REAL,
    balance_limit        REAL,
    balance_iso_currency TEXT,
    last_refresh   TEXT,
    FOREIGN KEY (item_id) REFERENCES items(item_id)
);

CREATE TABLE IF NOT EXISTS holdings (
    -- Composite PK: one row per (account, security) pair on a given refresh
    account_id     TEXT NOT NULL,
    security_id    TEXT NOT NULL,
    ticker         TEXT,                    -- "VTI", "CRWV", null for cash
    name           TEXT,                    -- "Vanguard Total Stock Market ETF"
    security_type  TEXT,                    -- "equity" | "etf" | "mutual fund" | "cash" | "fixed income"
    quantity       REAL NOT NULL,
    institution_price        REAL,
    institution_value        REAL,
    cost_basis     REAL,
    iso_currency   TEXT,
    last_refresh   TEXT NOT NULL,
    PRIMARY KEY (account_id, security_id, last_refresh),
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    account_id     TEXT NOT NULL,
    institution    TEXT NOT NULL,
    date           TEXT NOT NULL,           -- YYYY-MM-DD
    amount         REAL NOT NULL,           -- negative = inflow (Plaid convention)
    iso_currency   TEXT,
    name           TEXT,                    -- merchant / description
    category       TEXT,                    -- top-level Plaid category
    subcategory    TEXT,
    pending        INTEGER NOT NULL DEFAULT 0,
    inserted_at    TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE INDEX IF NOT EXISTS idx_holdings_account ON holdings(account_id);
CREATE INDEX IF NOT EXISTS idx_holdings_ticker ON holdings(ticker);
CREATE INDEX IF NOT EXISTS idx_transactions_account_date ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_accounts_institution ON accounts(institution);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Connection context manager with foreign keys + row factory."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_last_refresh(db_path: Path) -> str | None:
    """Return the most recent refresh timestamp across all items, or None."""
    with connect(db_path) as conn:
        row = conn.execute("SELECT MAX(last_refresh) AS ts FROM items").fetchone()
        return row["ts"] if row and row["ts"] else None
