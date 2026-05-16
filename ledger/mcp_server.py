"""ledger MCP server.

Exposes a small set of tools that AI agents (Claude Code, etc.) call to
inspect the user's financial state. Stale-check semantics: any tool that
reads holdings/balances first checks last_refresh against stale_minutes;
if stale, calls Plaid to refresh before serving.

Tools exposed:
- get_summary()                 — high-level: institutions, accounts, total balance
- get_accounts()                — all accounts with balances
- get_holdings(account?)        — per-position holdings, optionally filtered to one account
- get_holdings_by_ticker(t)     — aggregate one ticker across all accounts
- get_transactions(since, ...)  — recent transactions, optionally filtered
- refresh_all(force?)           — force-refresh from Plaid, returns counts
- get_status()                  — what's connected, when each item last refreshed
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from . import db, refresh
from .config import Config


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _is_stale(last_refresh: str | None, stale_minutes: int) -> bool:
    if not last_refresh:
        return True
    dt = _parse_iso(last_refresh)
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - dt
    return age > timedelta(minutes=stale_minutes)


def _ensure_fresh(cfg: Config, force: bool = False) -> dict[str, Any]:
    """Refresh from Plaid if stale or forced. Returns a status dict."""
    last = db.get_last_refresh(cfg.db_path)
    if not force and not _is_stale(last, cfg.stale_minutes):
        return {"refreshed": False, "last_refresh": last, "reason": "cache-fresh"}

    results = refresh.refresh_all(cfg)
    return {
        "refreshed": True,
        "items": [
            {
                "institution": r.institution,
                "accounts": r.accounts_count,
                "holdings": r.holdings_count,
                "transactions_added": r.transactions_added,
                "error": r.error,
            }
            for r in results
        ],
    }


# ── Read helpers (return Python dicts/lists; serialized to text by tool layer) ──

def _rows_to_list(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def get_summary(cfg: Config) -> dict[str, Any]:
    with db.connect(cfg.db_path) as conn:
        items = _rows_to_list(conn.execute(
            "SELECT institution, last_refresh FROM items WHERE status = 'active'"
        ).fetchall())
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS account_count,
                SUM(CASE WHEN type IN ('depository','investment')
                    THEN COALESCE(balance_current,0) ELSE 0 END) AS assets,
                SUM(CASE WHEN type IN ('credit','loan')
                    THEN COALESCE(balance_current,0) ELSE 0 END) AS liabilities
            FROM accounts
            """
        ).fetchone()
        return {
            "institutions": items,
            "accounts": totals["account_count"],
            "total_assets": totals["assets"] or 0,
            "total_liabilities": totals["liabilities"] or 0,
            "net_worth": (totals["assets"] or 0) - (totals["liabilities"] or 0),
        }


def get_accounts(cfg: Config) -> list[dict[str, Any]]:
    with db.connect(cfg.db_path) as conn:
        return _rows_to_list(conn.execute(
            """
            SELECT institution, name, official_name, type, subtype, mask,
                   balance_current, balance_available, balance_limit,
                   balance_iso_currency, last_refresh
            FROM accounts
            ORDER BY institution, type, name
            """
        ).fetchall())


def get_holdings(cfg: Config, account_id: str | None = None) -> list[dict[str, Any]]:
    """Most-recent holdings per (account, security)."""
    with db.connect(cfg.db_path) as conn:
        where = "WHERE a.account_id = ?" if account_id else ""
        params: tuple = (account_id,) if account_id else ()
        sql = f"""
            SELECT a.institution, a.name AS account_name, a.subtype,
                   h.ticker, h.name AS security_name, h.security_type,
                   h.quantity, h.institution_price, h.institution_value,
                   h.cost_basis, h.iso_currency, h.last_refresh
            FROM holdings h
            JOIN accounts a ON a.account_id = h.account_id
            JOIN (
                SELECT account_id, security_id, MAX(last_refresh) AS max_ts
                FROM holdings GROUP BY account_id, security_id
            ) latest ON latest.account_id = h.account_id
                    AND latest.security_id = h.security_id
                    AND latest.max_ts = h.last_refresh
            {where}
            ORDER BY a.institution, a.name, h.ticker
        """
        return _rows_to_list(conn.execute(sql, params).fetchall())


def get_holdings_by_ticker(cfg: Config, ticker: str) -> list[dict[str, Any]]:
    rows = get_holdings(cfg)
    return [r for r in rows if (r.get("ticker") or "").upper() == ticker.upper()]


def get_transactions(
    cfg: Config,
    since: str | None = None,
    limit: int = 100,
    account_id: str | None = None,
) -> list[dict[str, Any]]:
    with db.connect(cfg.db_path) as conn:
        conditions = []
        params: list = []
        if since:
            conditions.append("date >= ?")
            params.append(since)
        if account_id:
            conditions.append("account_id = ?")
            params.append(account_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT transaction_id, account_id, institution, date, amount,
                   iso_currency, name, category, subcategory, pending
            FROM transactions
            {where}
            ORDER BY date DESC, transaction_id DESC
            LIMIT ?
        """
        params.append(limit)
        return _rows_to_list(conn.execute(sql, params).fetchall())


def get_status(cfg: Config) -> dict[str, Any]:
    with db.connect(cfg.db_path) as conn:
        items = _rows_to_list(conn.execute(
            "SELECT institution, status, last_refresh FROM items"
        ).fetchall())
        return {
            "items": items,
            "db_path": str(cfg.db_path),
            "stale_minutes": cfg.stale_minutes,
        }


# ── MCP wiring ──

def build_server(cfg: Config) -> Server:
    server = Server("ledger")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_summary",
                description="Net worth + institution list + account count. "
                            "Refreshes from Plaid if cache is stale.",
                inputSchema={"type": "object", "properties": {
                    "force_refresh": {"type": "boolean", "default": False}
                }},
            ),
            Tool(
                name="get_accounts",
                description="All accounts with current balances. "
                            "Refreshes from Plaid if cache is stale.",
                inputSchema={"type": "object", "properties": {
                    "force_refresh": {"type": "boolean", "default": False}
                }},
            ),
            Tool(
                name="get_holdings",
                description="Per-position investment holdings across all "
                            "brokerages, or filtered to one account_id.",
                inputSchema={"type": "object", "properties": {
                    "account_id": {"type": "string"},
                    "force_refresh": {"type": "boolean", "default": False},
                }},
            ),
            Tool(
                name="get_holdings_by_ticker",
                description="Aggregate one ticker symbol across all brokerage "
                            "accounts. Returns one row per account that holds it.",
                inputSchema={"type": "object", "properties": {
                    "ticker": {"type": "string"},
                    "force_refresh": {"type": "boolean", "default": False},
                }, "required": ["ticker"]},
            ),
            Tool(
                name="get_transactions",
                description="Recent transactions, newest first. Filter by "
                            "since (YYYY-MM-DD) or account_id.",
                inputSchema={"type": "object", "properties": {
                    "since": {"type": "string"},
                    "account_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                    "force_refresh": {"type": "boolean", "default": False},
                }},
            ),
            Tool(
                name="refresh_all",
                description="Force-refresh all accounts from Plaid right now. "
                            "Use when you want guaranteed-fresh data.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="get_status",
                description="Show which institutions are connected and when "
                            "each was last refreshed. Does NOT refresh.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        force = bool(arguments.get("force_refresh", False))

        if name == "get_summary":
            _ensure_fresh(cfg, force=force)
            data = get_summary(cfg)
        elif name == "get_accounts":
            _ensure_fresh(cfg, force=force)
            data = get_accounts(cfg)
        elif name == "get_holdings":
            _ensure_fresh(cfg, force=force)
            data = get_holdings(cfg, arguments.get("account_id"))
        elif name == "get_holdings_by_ticker":
            _ensure_fresh(cfg, force=force)
            data = get_holdings_by_ticker(cfg, arguments["ticker"])
        elif name == "get_transactions":
            _ensure_fresh(cfg, force=force)
            data = get_transactions(
                cfg,
                since=arguments.get("since"),
                limit=int(arguments.get("limit", 100)),
                account_id=arguments.get("account_id"),
            )
        elif name == "refresh_all":
            data = _ensure_fresh(cfg, force=True)
        elif name == "get_status":
            data = get_status(cfg)
        else:
            return [TextContent(type="text", text=f"unknown tool: {name}")]

        import json
        return [TextContent(type="text", text=json.dumps(data, default=str, indent=2))]

    return server


async def _run() -> None:
    cfg = Config.load()
    db.init_db(cfg.db_path)
    server = build_server(cfg)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
