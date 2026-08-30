"""Verify the configured database, without ever printing its connection string."""

from __future__ import annotations

import json
import sys

from sqlalchemy.exc import SQLAlchemyError

from . import database


def main() -> int:
    try:
        database.init_db()
        backend = database.verify_connection()
    except SQLAlchemyError:
        # Database exceptions may include portions of a connection URL. Keep diagnostics useful
        # without turning a password into terminal output, a screenshot, or a chat attachment.
        print("Could not connect to the configured database. Check DATABASE_URL in ingest/.env.", file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "database": backend, "tables": "ready"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
