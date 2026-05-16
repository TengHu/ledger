"""One-time Plaid Link OAuth flow.

Run once per account you want to connect. Launches a local Flask server
on $LEDGER_PORT (default 8765), opens a browser to localhost:$PORT,
serves a page with the Plaid Link widget. After the user clicks through
their bank's OAuth flow, the public_token is exchanged for an
access_token (stored in OS keyring via tokens.py) and an item row is
written to the DB.

Usage:
    python -m ledger.connect           # interactive: opens browser
    Repeat for each institution. Ctrl+C when done.
"""

from __future__ import annotations

import webbrowser

from flask import Flask, jsonify, render_template, request

from . import db, plaid_client, tokens
from .config import Config


def _list_connected_institutions(cfg: Config) -> list[str]:
    with db.connect(cfg.db_path) as conn:
        rows = conn.execute(
            "SELECT institution FROM items WHERE status = 'active' "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [row["institution"] for row in rows]


def make_app(cfg: Config) -> Flask:
    app = Flask(__name__)
    client = plaid_client.make_client(cfg)

    @app.route("/")
    def index():
        link_token = plaid_client.create_link_token(client)
        return render_template(
            "link.html",
            link_token=link_token,
            connected=_list_connected_institutions(cfg),
        )

    @app.route("/exchange", methods=["POST"])
    def exchange():
        payload = request.get_json(force=True)
        public_token = payload.get("public_token")
        institution_name = payload.get("institution_name", "Unknown")
        if not public_token:
            return jsonify(ok=False, error="missing public_token"), 400

        try:
            access_token, item_id = plaid_client.exchange_public_token(
                client, public_token
            )
            tokens.save_token(item_id, access_token)
            with db.connect(cfg.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO items "
                    "(item_id, institution, created_at, status) "
                    "VALUES (?, ?, ?, 'active')",
                    (item_id, institution_name, db.now_iso()),
                )
            return jsonify(ok=True, item_id=item_id, institution=institution_name)
        except Exception as exc:
            return jsonify(ok=False, error=str(exc)), 500

    return app


def main() -> None:
    cfg = Config.load()
    db.init_db(cfg.db_path)
    app = make_app(cfg)

    url = f"http://localhost:{cfg.port}/"
    print(f"\nledger connect — Plaid Link flow")
    print(f"Opening {url} in your browser.")
    print(f"Click 'Connect a new account' for each institution.")
    print(f"Press Ctrl+C here when done.\n")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=cfg.port, debug=False)


if __name__ == "__main__":
    main()
