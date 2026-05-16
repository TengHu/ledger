# ledger architecture

## Purpose

Aggregate the user's banking + brokerage + retirement accounts into a
local SQLite database, expose it via MCP, refresh on demand from the
agent. Goal: same data depth as Empower, but the database lives on the
user's machine and every line of code outside Plaid's bank-connection
layer is auditable.

## Components

```
┌───────────────────────────────────────────────────────────────┐
│  ONE-TIME SETUP (per institution)                             │
│                                                               │
│  ledger.connect                                               │
│    ↓ launches Flask on localhost:8765                         │
│    ↓ serves templates/link.html with Plaid Link widget        │
│    ↓ user clicks "Connect" → OAuth flow inside Plaid Link     │
│    ↓ Plaid returns public_token via JS callback               │
│    ↓ /exchange endpoint: public_token → access_token          │
│    ↓ access_token → keyring (macOS keychain)                  │
│    ↓ item_id + institution_name → items table in SQLite       │
└───────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────┐
│  REFRESH (called by MCP or CLI)                               │
│                                                               │
│  ledger.refresh.refresh_all(cfg)                              │
│    ↓ for each active item:                                    │
│       ↓ load access_token from keyring                        │
│       ↓ accounts_balance_get → write accounts table           │
│       ↓ investments_holdings_get → write holdings table       │
│       ↓ transactions_sync → write transactions table          │
│       ↓ update items.last_refresh                             │
└───────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────┐
│  QUERY (called by AI agent via MCP)                           │
│                                                               │
│  Agent calls mcp__ledger__get_summary()                       │
│    ↓ MCP server checks db.items.last_refresh                  │
│    ↓ if older than stale_minutes (default 60): refresh        │
│    ↓ else: serve from SQLite                                  │
│    ↓ return JSON to agent                                     │
└───────────────────────────────────────────────────────────────┘
```

## Storage layout

```
~/Code/ledger/db.sqlite       ← all positions, transactions, balances
  tables: items, accounts, holdings, transactions

macOS keychain (via keyring lib)
  service: "ledger.plaid"
  account: <plaid item_id>
  password: <plaid access_token>

~/Code/ledger/.env             ← PLAID_CLIENT_ID, PLAID_SECRET
                                 (gitignored, never committed)
```

## Trust boundaries

| Layer | Sees | Trust required |
|---|---|---|
| Your bank | Your bank login (via Plaid OAuth) | You already trust them |
| Plaid | OAuth refresh tokens for your accounts | You trust them with token storage; they don't see passwords (OAuth) |
| ledger/ Python code | Plaid API responses, written to your DB | 100% your machine, 100% open source |
| `.env` | Plaid client_id + secret | Your file, your machine, gitignored |
| `db.sqlite` | Full positions, transactions, balances | Your file, your machine |
| Keychain | Plaid access tokens | OS-level encrypted store |
| MCP server | Reads DB, calls refresh.refresh_all | Spawned by Claude Code locally |
| AI agent | JSON responses from MCP tools | Whatever you've authorized your agent to access |

Nothing about your account data leaves your machine except the Plaid API
calls themselves (your machine → Plaid → bank). Plaid sees the data
in-flight but does not store positions long-term; they cache for
performance.

## Refresh policy

The MCP server's `_ensure_fresh()` decides:
- If `force_refresh=True` in the tool call → refresh
- If `last_refresh` is null (never refreshed) → refresh
- If `last_refresh` is older than `LEDGER_STALE_MINUTES` (default 60) → refresh
- Else → serve cached SQLite

This means the first agent query of a session typically triggers a fresh
pull from Plaid (30-60 sec). Subsequent queries within the same hour use
the cached snapshot (~instant). Manual `mcp__ledger__refresh_all` forces
a refresh any time.

## Why not just write a UI like Empower?

Because the user already has an agent. The agent IS the UI. Every
question Empower's dashboard could answer ("am I overweight tech?" "how
much cash do I have?" "show me last quarter's dividends") is a tool call
the agent makes against ledger. No UI needed.

## Why not just use SimpleFIN + Actual Budget?

SimpleFIN refreshes once a day on its own schedule. Can't force a fresh
pull at session start. Killed by the "refresh on demand at agent session
start" requirement.

## Why not pure DIY (browser scraping)?

None of the user's 4 accounts (Wells, Vanguard, Robinhood, Fidelity)
expose a personal API. Browser scraping works but:
- Vanguard's anti-bot detection breaks raw Playwright
- Wells/Fidelity OFX is monthly download, not real-time
- robin_stocks for Robinhood is TOS-grey (Robinhood itself uses Plaid)
- Maintenance is real (every bank UI change breaks the scraper)

Plaid is the one piece you cannot realistically self-host given US bank
API reality. Everything ELSE is self-hosted in ledger.

## Future extensions

- **Theme tagging.** A `holding_tags` table joins `holdings.security_id`
  to user-defined theme tags (`ai-infra`, `storage`, `space`). Pod's
  `/pod-portfolio-exposure` skill can then query
  `mcp__ledger__get_exposure_by_theme(theme)` to compute net-worth-
  weighted theme exposure across all brokerage accounts.

- **Cost basis tracking.** Plaid returns cost_basis in the holdings
  response, but it's not always populated for older positions. Could
  augment with a `holding_lots` table the user populates manually for
  positions Plaid doesn't have.

- **Encrypted DB.** SQLite has SQLCipher; could swap the connection
  layer to encrypt-at-rest if the OS keychain isn't sufficient.

- **Multi-user.** Not currently in scope. The `keyring` service name
  could be parameterized to support multiple users on one machine.

## Versioning

Single version field in `pyproject.toml`. No semver discipline yet —
this is personal-tier software. Bump as needed.
