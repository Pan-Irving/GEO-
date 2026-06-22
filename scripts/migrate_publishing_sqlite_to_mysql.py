#!/usr/bin/env python
"""Migrate the publishing workbench SQLite database into the configured SQL database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import func, select


ROOT = Path(__file__).resolve().parents[1]
PUBLISHING_BACKEND = ROOT / "publishing" / "backend"
sys.path.insert(0, str(PUBLISHING_BACKEND))

from app.config import get_settings  # noqa: E402
from app.db import article_snapshots, assignments, publication_records, sessions, users, PublishingStore  # noqa: E402


TABLES = [
    ("users", users),
    ("sessions", sessions),
    ("article_snapshots", article_snapshots),
    ("assignments", assignments),
    ("publication_records", publication_records),
]


def sqlite_rows(path: Path, table_name: str) -> list[dict]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate publishing SQLite data into the configured SQL database.")
    parser.add_argument("--sqlite-path", type=Path, default=None, help="Path to the old publishing.db file.")
    parser.add_argument("--dry-run", action="store_true", help="Only print table counts, do not write.")
    parser.add_argument("--force", action="store_true", help="Allow importing into a non-empty target database.")
    args = parser.parse_args()

    settings = get_settings()
    sqlite_path = args.sqlite_path or settings.database_path
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")
    if not settings.publishing_database_url:
        raise SystemExit("Set PUBLISHING_DATABASE_URL to the MySQL target before running migration.")

    store = PublishingStore(settings)
    counts = {name: len(sqlite_rows(sqlite_path, name)) for name, _table in TABLES}
    print("Source SQLite:", sqlite_path)
    print("Target:", settings.publishing_database_url)
    for name, count in counts.items():
        print(f"{name}: {count}")
    if args.dry_run:
        return 0

    with store.engine.begin() as conn:
        counts_on_target = {name: conn.execute(select(func.count()).select_from(table)).scalar_one() for name, table in TABLES}
        target_count = sum(counts_on_target.values())
        seeded_admin_only = (
            counts_on_target["users"] == 1
            and all(counts_on_target[name] == 0 for name in counts_on_target if name != "users")
        )
        if target_count and not seeded_admin_only and not args.force:
            raise SystemExit("Target database already has users. Re-run with --force if this is intentional.")
        for name, table in TABLES:
            rows = sqlite_rows(sqlite_path, name)
            if not rows:
                continue
            conn.execute(table.delete())
            conn.execute(table.insert(), rows)
            print(f"Imported {len(rows)} rows into {name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
