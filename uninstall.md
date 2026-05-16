# ledger — uninstall procedure

**For an AI assistant to read and follow.** Removes ledger's MCP
registration and local data. Plaid items must be deleted manually from
the Plaid dashboard.

When you need user input, use `AskUserQuestion`. Never plain chat prompts.
If AUQ is unavailable, BLOCKED.

---

## Step 1: Detect state

```bash
[ -d "$HOME/Code/ledger" ] && echo "LEDGER_INSTALLED" || echo "LEDGER_GONE"
[ -f "$HOME/Code/ledger/db.sqlite" ] && echo "DB_EXISTS" || echo "DB_GONE"
grep -l '"ledger"' "$HOME/.mcp.json" 2>/dev/null && echo "GLOBAL_MCP_HAS_LEDGER"
```

If `LEDGER_GONE`, tell the user nothing to uninstall and stop.

---

## Step 2: Confirm scope

```
D1 — What should I remove?
ELI10: There are three layers. The MCP entry tells Claude Code to load
       ledger. The local DB holds your account data. The OS keychain
       holds Plaid OAuth tokens. The source code at ~/Code/ledger/ is
       separate. Plaid items (on Plaid's side) require manual deletion.
Options:
A) Remove MCP entry only (keep code + DB + keychain tokens for later use)
B) Remove MCP entry + local DB (keep code + keychain tokens)
C) Remove everything local (MCP + DB + keychain tokens). Code stays.
D) Remove everything local + delete the source repo at ~/Code/ledger
E) Cancel
```

If E, stop.

---

## Step 3: Remove MCP entry (always, unless cancel)

Read the user's MCP config files (`~/.mcp.json`, any project-local
`.mcp.json` you can find that has a `ledger` entry). Remove the
`mcpServers.ledger` key from each. Write back. Do not touch other entries.

If the file has only the `ledger` entry and nothing else under
`mcpServers`, leave the file with an empty `mcpServers` object — do not
delete the file.

---

## Step 4: Remove local DB (if B/C/D)

```bash
rm -f "$HOME/Code/ledger/db.sqlite" "$HOME/Code/ledger/db.sqlite-journal"
```

This deletes your account snapshot. Plaid still has tokens; the next
refresh would recreate the DB from scratch. Idempotent.

---

## Step 5: Remove keychain tokens (if C/D)

```bash
cd "$HOME/Code/ledger"
source .venv/bin/activate 2>/dev/null || true
python3 -c "
from ledger import tokens, db
from ledger.config import Config
import sqlite3
try:
    cfg = Config.load()
    if cfg.db_path.exists():
        with sqlite3.connect(cfg.db_path) as conn:
            for (item_id,) in conn.execute('SELECT item_id FROM items'):
                tokens.delete_token(item_id)
                print(f'deleted token for {item_id}')
except Exception as e:
    # If config or DB is already gone, fall back to keychain enumeration
    # (best-effort — keyring doesn't have a list-all API)
    print(f'note: {e}')
" 2>/dev/null || true
```

If `.venv` is already gone, the loop won't run. Keychain entries under
service `ledger.plaid` may remain. Tell the user to clean these manually
via Keychain Access.app on macOS if they want a truly clean wipe.

---

## Step 6: Remove source repo (if D)

```
D2 — Confirm removal of ~/Code/ledger source repo?
ELI10: Deletes the entire ledger codebase. Reversible only by re-cloning
       from GitHub (if it was pushed) or re-scaffolding. Code is the only
       thing being deleted; book/, pod, and other projects untouched.
Options:
A) Yes, delete source
B) No, keep source
```

If A:

```bash
rm -rf "$HOME/Code/ledger"
```

---

## Step 7: Plaid dashboard cleanup (manual, always recommended)

Tell the user:

```
Plaid items on Plaid's side are NOT deleted by this uninstall. To fully
disconnect:

1. Visit https://dashboard.plaid.com/
2. Sign in
3. Find each connected item (your Wells / Fidelity / Vanguard / Robinhood)
4. Delete each item

This revokes the OAuth tokens on Plaid's side. ledger doesn't have
permission to do this for you because the Plaid /item/remove API needs
the access token, and we may have already deleted those from the
keychain.
```

---

## Step 8: Report

```
ledger uninstalled.

Removed:
  - MCP entry from <files touched>
  - <DB / keychain tokens / source repo> per your choice

Still on Plaid's side:
  - Connected items at https://dashboard.plaid.com/ — delete manually
    if you want a full disconnect

Reinstall: follow ~/Code/ledger/setup.md (if source still exists) or
re-clone the repo and run setup.md.
```

---

## Notes for the AI running this

- Never auto-delete the source repo without explicit AUQ confirmation.
- Plaid items on Plaid's side are out of scope for automated removal.
  Always remind the user about manual dashboard cleanup.
- When you need user input, always use `AskUserQuestion`. Never plain
  chat prompts. If AUQ is unavailable, BLOCKED.
