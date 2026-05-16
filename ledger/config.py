"""Config loading: env vars, paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (parent of this file's parent).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Config:
    plaid_client_id: str
    plaid_secret: str
    plaid_env: str  # "sandbox" | "development" | "production"
    db_path: Path
    port: int
    stale_minutes: int
    project_root: Path

    @classmethod
    def load(cls) -> "Config":
        missing = []
        client_id = os.environ.get("PLAID_CLIENT_ID", "").strip()
        secret = os.environ.get("PLAID_SECRET", "").strip()
        if not client_id:
            missing.append("PLAID_CLIENT_ID")
        if not secret:
            missing.append("PLAID_SECRET")
        if missing:
            raise RuntimeError(
                f"Missing required env vars: {', '.join(missing)}. "
                f"Copy .env.example to .env and fill in your Plaid keys."
            )

        env = os.environ.get("PLAID_ENV", "production").strip().lower()
        if env not in ("sandbox", "development", "production"):
            raise RuntimeError(
                f"PLAID_ENV must be sandbox|development|production, got: {env}"
            )

        db_path_str = os.environ.get("LEDGER_DB_PATH", "").strip()
        db_path = Path(db_path_str) if db_path_str else (PROJECT_ROOT / "db.sqlite")

        port = int(os.environ.get("LEDGER_PORT", "8765"))
        stale_minutes = int(os.environ.get("LEDGER_STALE_MINUTES", "60"))

        return cls(
            plaid_client_id=client_id,
            plaid_secret=secret,
            plaid_env=env,
            db_path=db_path,
            port=port,
            stale_minutes=stale_minutes,
            project_root=PROJECT_ROOT,
        )
