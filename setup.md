# ledger — install procedure

**For an AI assistant to read and follow.** Goal: get ledger running on the
user's machine, connected to their Plaid accounts, and registered as an MCP
server in their Claude Code config.

When the skill needs input from the user, use AskUserQuestion. Never plain
chat prompts. If AUQ is unavailable, stop and report
`BLOCKED — AskUserQuestion unavailable`.

---

## Inputs

- Project lives at `~/Code/ledger/` (default; ask user if different).
- The user has a Plaid developer account or is willing to create one.
- The user has the institutions they want to connect ready (Wells, Fidelity,
  Vanguard, Robinhood — confirm via AUQ before launching the auth flow).

---

## Step 0: Detect state

```bash
[ -d "$HOME/Code/ledger" ] && echo "LEDGER_DIR_OK" || echo "LEDGER_DIR_MISSING"
[ -f "$HOME/Code/ledger/.env" ] && echo "ENV_OK" || echo "ENV_MISSING"
[ -f "$HOME/Code/ledger/db.sqlite" ] && echo "DB_EXISTS" || echo "DB_NEW"
which python3 && python3 --version
which uv || echo "NO_UV"
```

If `LEDGER_DIR_MISSING`: this procedure expects ledger source at
`~/Code/ledger/`. Stop and tell the user the source isn't where it's expected.

---

## Step 1: Virtualenv + install

If `uv` is installed (preferred — fast), use it. Otherwise fall back to
`python3 -m venv`.

```bash
cd "$HOME/Code/ledger"

if command -v uv >/dev/null 2>&1; then
  uv venv .venv
  source .venv/bin/activate
  uv pip install -e .
else
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -e .
fi
```

Idempotent. Re-running is safe.

---

## Step 2: Plaid developer account

If `ENV_MISSING`, the user needs Plaid API credentials. AskUserQuestion:

```
D1 — Do you have Plaid API credentials yet?
ELI10: Plaid is the aggregator that connects to your banks. They issue
       a client_id + secret you put in .env. Free for personal use.
Options:
A) Yes, I have client_id and secret
B) No, walk me through signup
C) Cancel — I'll do this manually later
```

If A: tell the user to `cp .env.example .env` and fill in PLAID_CLIENT_ID and
PLAID_SECRET. Wait for them to confirm. Then proceed.

If B: walk them through:
1. Visit https://dashboard.plaid.com/signup
2. Sign up (free)
3. Confirm email
4. After login, go to Team Settings → Keys
5. Copy `client_id` and the `Production` secret (NOT sandbox if they want real data)
6. `cp .env.example .env` and paste them in
7. Set `PLAID_ENV=production`

Note: production keys may require Plaid to approve the use case. For
personal use ("aggregating my own accounts"), this is typically auto-approved
or approved within hours. If pending, suggest starting with `PLAID_ENV=sandbox`
to verify the install works against fake data first.

If C: stop. Tell the user to come back when they have Plaid keys.

---

## Step 3: Verify .env loads

```bash
cd "$HOME/Code/ledger"
source .venv/bin/activate
python -c "from ledger.config import Config; c = Config.load(); print(f'env={c.plaid_env}, db={c.db_path}')"
```

Should print something like `env=production, db=/Users/.../Code/ledger/db.sqlite`
without errors. If it errors with "Missing required env vars", the .env file
is incomplete — go back to Step 2.

---

## Step 4: Run the one-time Plaid Link auth

This launches a local Flask server and opens a browser. The user clicks
"Connect a new account" once per institution, completes their bank's OAuth
flow inside the Plaid Link widget, and the access token gets stored in the
OS keychain.

Before running, AskUserQuestion:

```
D2 — Ready to connect your accounts?
ELI10: This opens a browser to localhost:8765 with a "Connect a new
       account" button. Click it once per institution (Wells, Fidelity,
       Vanguard, Robinhood). After each one, the page reloads showing
       it as connected. Press Ctrl+C in the terminal when done.
Options:
A) Yes, start the connect flow
B) Not now
```

If A:

```bash
cd "$HOME/Code/ledger"
source .venv/bin/activate
python -m ledger.connect
```

This blocks on the Flask server. Tell the user: "Browser will open. Connect
each account, then come back and tell me when you're done — I'll Ctrl+C the
server for you and continue."

When the user confirms they're done, you (the AI) cannot send Ctrl+C from
inside this skill. Tell the user to press Ctrl+C in the terminal where they
ran `python -m ledger.connect`, then return here.

If B: skip this step. Tell them they can run `python -m ledger.connect`
later.

---

## Step 5: First refresh (verify data flows)

```bash
cd "$HOME/Code/ledger"
source .venv/bin/activate
python -m ledger.refresh
```

Should print one line per connected item:

```
  OK   Wells Fargo          accounts=2  holdings=0   transactions_added=47
  OK   Vanguard             accounts=3  holdings=15  transactions_added=8
  OK   Robinhood            accounts=1  holdings=22  transactions_added=12
  OK   Fidelity             accounts=4  holdings=31  transactions_added=19
```

If any institution shows `FAIL ... no access_token in keyring`, the connect
flow didn't complete for that institution. Re-run Step 4.

---

## Step 6: Register MCP server with Claude Code

The user's MCP config is in `~/.mcp.json` (global) or
`<project>/.mcp.json` (project-local). AskUserQuestion:

```
D3 — Where should ledger's MCP server be registered?
ELI10: Global means every Claude Code session sees ledger. Project-local
       means only when working in a specific project (e.g., ~/Code/hedge-fund).
Options:
A) Global (~/.mcp.json) — ledger available everywhere
B) Project-local in ~/Code/hedge-fund/.mcp.json — only in the fund workspace
C) Both
```

For the chosen file(s), merge in this MCP server config block:

```json
{
  "mcpServers": {
    "ledger": {
      "command": "/Users/<USER>/Code/ledger/.venv/bin/python",
      "args": ["-m", "ledger.mcp_server"],
      "env": {}
    }
  }
}
```

Substitute the real absolute path to the venv Python. Read the existing
file (if any), merge the `mcpServers.ledger` key, write it back. Do not
overwrite other entries.

---

## Step 7: Smoke test

Tell the user: "Restart Claude Code (or close + reopen this session). Then
try asking: 'What are my current holdings via ledger?'"

The first call will trigger a fresh refresh from Plaid (~30-60 seconds for
4 institutions). Subsequent calls within 60 minutes use the cached SQLite.

---

## Step 8: Report

```
ledger installed.

Connected:
  Wells Fargo, Vanguard, Robinhood, Fidelity (or whatever subset)

MCP tools now available in Claude Code:
  mcp__ledger__get_summary
  mcp__ledger__get_accounts
  mcp__ledger__get_holdings
  mcp__ledger__get_holdings_by_ticker
  mcp__ledger__get_transactions
  mcp__ledger__refresh_all
  mcp__ledger__get_status

Manual refresh (if you want to skip the agent path):
  cd ~/Code/ledger && source .venv/bin/activate && python -m ledger.refresh

Add another account later:
  cd ~/Code/ledger && source .venv/bin/activate && python -m ledger.connect

Uninstall:
  Follow ~/Code/ledger/uninstall.md
```

---

## Notes for the AI running this

- Idempotent — re-running any step is safe.
- The OS keychain (via the `keyring` library) holds Plaid access tokens.
  Never log them, never echo them.
- The `.env` file holds `PLAID_CLIENT_ID` and `PLAID_SECRET`. Already in
  `.gitignore`. Do not paste these into chat output.
- Plaid Production keys may require Plaid approval. If the user is in pending
  state, suggest sandbox mode for now (set PLAID_ENV=sandbox) so they can
  verify the install works against fake data, then switch back to production
  when approved.
- When you need user input, always use `AskUserQuestion`. Never plain chat
  prompts. If AUQ is unavailable, BLOCKED.
