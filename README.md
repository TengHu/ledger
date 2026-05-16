# ledger

> Your accounts in one place. Plaid-backed, locally hosted, MCP-native.

A personal financial aggregator MCP server. Connect your bank, brokerage, and
retirement accounts via Plaid; data flows into a local SQLite DB on your
machine; AI assistants (Claude Code, etc.) query it via MCP.

**No cloud. No daily sync. No third-party UI.** Refresh on demand from your
agent. Same data depth as Empower (per-position holdings, cost basis,
transactions), but the database lives on your laptop.

## Status

Initial scaffold. Functional but not yet polished. See `setup.md` for the
install procedure (read by an AI assistant or followed manually).

## Why this exists

Empower / Personal Capital / Monarch all give you a holistic view of your
financial life, but the data lives on their servers in a UI you can't extend.
ledger gives you the same depth of data with three differences:

1. **Local-only storage.** All positions, transactions, balances live in
   `~/Code/ledger/db.sqlite` on your machine.
2. **MCP-native.** Any AI assistant that speaks MCP can query your holdings,
   net worth, exposure. Built for [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
   but works with any MCP client.
3. **On-demand refresh.** No cron, no background job. Refresh happens when
   your agent asks for it.

## How it works

```
You ──→ Plaid Link (one-time per account)
            │
            └─→ Plaid stores OAuth tokens (encrypted on Plaid's side)

Pod / agent ──→ MCP query: "what are my holdings?"
                    │
                    ▼
               ledger MCP server
                    │
                    ├─ if cache is stale → call Plaid → write SQLite
                    └─ if cache is fresh → return SQLite snapshot
```

Plaid handles the bank-connection layer (the part you can't realistically
self-host). ledger handles everything else: the database schema, the
refresh policy, the MCP exposure, the data depth.

## Stack

- **Python 3.11+** (stdlib + minimal deps)
- **Plaid Python SDK** — official, MIT-licensed
- **SQLite** — stdlib, single-file DB
- **Flask** — for the one-time Plaid Link OAuth flow (browser-required)
- **MCP Python SDK** — official Anthropic SDK
- **keyring** — OS-native token storage (macOS keychain, etc.)

## Install

Follow `setup.md`. Either read it yourself or paste it into an AI agent:

> Install ledger by following `~/Code/ledger/setup.md`.

The procedure handles: virtualenv creation, dep install, Plaid signup
walkthrough, one-time Plaid Link auth for your accounts, MCP config block
for Claude Code.

## Uninstall

Follow `uninstall.md`:

> Uninstall ledger by following `~/Code/ledger/uninstall.md`.

Removes the MCP entry. Plaid items must be deleted manually from
[dashboard.plaid.com](https://dashboard.plaid.com/) — ledger doesn't have
permission to delete accounts on Plaid's side.

## Architecture

See `docs/ARCHITECTURE.md` for the full data flow and design rationale.

## License

MIT.
