"""Pull fresh data from Plaid into the local SQLite DB.

Called by the MCP server when cache is stale or refresh is forced.
Iterates over every active item, fetches balances + holdings +
transactions, and writes them into the DB tables defined in db.py.

Holdings table is append-by-refresh — each refresh writes a new row per
(account, security, refresh_ts) tuple. This preserves history. MCP
queries typically use the most-recent refresh per account.

Transactions table uses transaction_id as PK with INSERT OR REPLACE,
so re-running sync is idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import db, plaid_client, tokens
from .config import Config


@dataclass
class RefreshResult:
    item_id: str
    institution: str
    accounts_count: int
    holdings_count: int
    transactions_added: int
    error: str | None = None


def refresh_all(cfg: Config | None = None) -> list[RefreshResult]:
    """Refresh every active item. Returns one RefreshResult per item."""
    cfg = cfg or Config.load()
    client = plaid_client.make_client(cfg)
    results: list[RefreshResult] = []

    with db.connect(cfg.db_path) as conn:
        items = conn.execute(
            "SELECT item_id, institution FROM items WHERE status = 'active'"
        ).fetchall()

    for item in items:
        item_id = item["item_id"]
        institution = item["institution"]
        access_token = tokens.get_token(item_id)
        if not access_token:
            results.append(RefreshResult(
                item_id=item_id, institution=institution,
                accounts_count=0, holdings_count=0, transactions_added=0,
                error="no access_token in keyring (re-run ledger-connect)",
            ))
            continue

        try:
            result = _refresh_one(cfg, client, item_id, institution, access_token)
            results.append(result)
        except Exception as exc:
            results.append(RefreshResult(
                item_id=item_id, institution=institution,
                accounts_count=0, holdings_count=0, transactions_added=0,
                error=str(exc),
            ))

    return results


def _refresh_one(
    cfg: Config,
    client,
    item_id: str,
    institution: str,
    access_token: str,
) -> RefreshResult:
    refresh_ts = db.now_iso()

    # --- Balances + accounts ---
    bal_response = plaid_client.get_balances(client, access_token)
    accounts_count = 0
    with db.connect(cfg.db_path) as conn:
        for acct in bal_response.accounts:
            balances = acct.balances
            conn.execute(
                """
                INSERT OR REPLACE INTO accounts
                (account_id, item_id, institution, name, official_name,
                 type, subtype, mask,
                 balance_current, balance_available, balance_limit,
                 balance_iso_currency, last_refresh)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    acct.account_id,
                    item_id,
                    institution,
                    acct.name,
                    getattr(acct, "official_name", None),
                    str(acct.type),
                    str(acct.subtype) if acct.subtype else None,
                    getattr(acct, "mask", None),
                    getattr(balances, "current", None),
                    getattr(balances, "available", None),
                    getattr(balances, "limit", None),
                    getattr(balances, "iso_currency_code", None),
                    refresh_ts,
                ),
            )
            accounts_count += 1

    # --- Investment holdings (per-position) ---
    holdings_count = 0
    try:
        h_response = plaid_client.get_holdings(client, access_token)
        sec_by_id = {s.security_id: s for s in h_response.securities}
        with db.connect(cfg.db_path) as conn:
            for h in h_response.holdings:
                sec = sec_by_id.get(h.security_id)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO holdings
                    (account_id, security_id, ticker, name, security_type,
                     quantity, institution_price, institution_value,
                     cost_basis, iso_currency, last_refresh)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        h.account_id,
                        h.security_id,
                        getattr(sec, "ticker_symbol", None) if sec else None,
                        getattr(sec, "name", None) if sec else None,
                        str(sec.type) if sec and sec.type else None,
                        h.quantity,
                        getattr(h, "institution_price", None),
                        getattr(h, "institution_value", None),
                        getattr(h, "cost_basis", None),
                        getattr(h, "iso_currency_code", None),
                        refresh_ts,
                    ),
                )
                holdings_count += 1
    except Exception:
        # Accounts without investment data (checking-only) return errors here.
        # Silently skip — accounts row was still written above.
        pass

    # --- Transactions (incremental via cursor) ---
    transactions_added = 0
    cursor: str | None = None
    while True:
        t_response = plaid_client.sync_transactions(client, access_token, cursor)
        with db.connect(cfg.db_path) as conn:
            for txn in t_response.added:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO transactions
                    (transaction_id, account_id, institution, date, amount,
                     iso_currency, name, category, subcategory, pending, inserted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        txn.transaction_id,
                        txn.account_id,
                        institution,
                        str(txn.date),
                        float(txn.amount),
                        getattr(txn, "iso_currency_code", None),
                        getattr(txn, "name", None),
                        (txn.personal_finance_category.primary
                         if getattr(txn, "personal_finance_category", None) else None),
                        (txn.personal_finance_category.detailed
                         if getattr(txn, "personal_finance_category", None) else None),
                        1 if getattr(txn, "pending", False) else 0,
                        refresh_ts,
                    ),
                )
                transactions_added += 1
        if not t_response.has_more:
            break
        cursor = t_response.next_cursor

    # --- Mark item refreshed ---
    with db.connect(cfg.db_path) as conn:
        conn.execute(
            "UPDATE items SET last_refresh = ? WHERE item_id = ?",
            (refresh_ts, item_id),
        )

    return RefreshResult(
        item_id=item_id,
        institution=institution,
        accounts_count=accounts_count,
        holdings_count=holdings_count,
        transactions_added=transactions_added,
    )


def main() -> None:
    """CLI: python -m ledger.refresh"""
    results = refresh_all()
    if not results:
        print("No items connected. Run `python -m ledger.connect` first.")
        return
    for r in results:
        if r.error:
            print(f"  FAIL {r.institution}: {r.error}")
        else:
            print(
                f"  OK   {r.institution:<20} "
                f"accounts={r.accounts_count} "
                f"holdings={r.holdings_count} "
                f"transactions_added={r.transactions_added}"
            )


if __name__ == "__main__":
    main()
