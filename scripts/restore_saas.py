"""Safely restore a verified PostgreSQL custom-format backup for a recovery drill.

This command deliberately requires an explicit confirmation and, by default,
only accepts target database names that look disposable (for example a
``*_restore`` or ``*_drill`` database).  A real production restore is possible
only with a second explicit override, so an operator cannot accidentally
replace the live database while rehearsing recovery.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

try:  # Supports both ``python scripts/restore_saas.py`` and module imports in tests.
    from scripts.postgres_urls import postgres_client_url
except ModuleNotFoundError:  # pragma: no cover - exercised by the Compose runtime.
    from postgres_urls import postgres_client_url


DISPOSABLE_DATABASE_MARKERS = ("restore", "recovery", "drill", "staging", "stage", "test")


def _database_name(database_url: str) -> str:
    parsed = urlparse(database_url)
    if not database_url.startswith("postgresql") or not parsed.path or parsed.path == "/":
        raise ValueError("DATABASE_URL must point to a named PostgreSQL database")
    return parsed.path.rsplit("/", 1)[-1].lower()


def restore_backup(
    database_url: str,
    archive: Path,
    *,
    confirmed: bool = False,
    allow_non_disposable_target: bool = False,
) -> None:
    """Restore ``archive`` after validating it and applying safety interlocks."""
    database_name = _database_name(database_url)
    client_url = postgres_client_url(database_url)
    if not archive.is_file():
        raise FileNotFoundError(f"backup archive not found: {archive}")
    if not confirmed:
        raise ValueError("pass --confirm-restore to acknowledge that the target database will be replaced")
    if not allow_non_disposable_target and not any(marker in database_name for marker in DISPOSABLE_DATABASE_MARKERS):
        raise ValueError(
            "target database must be a disposable restore/drill/staging/test database; "
            "pass --allow-non-disposable-target only during an approved production recovery"
        )

    # Verify readability before issuing any destructive restore command.
    subprocess.run(["pg_restore", "--list", str(archive)], check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges",
            "--exit-on-error", "--single-transaction", "--dbname", client_url, str(archive),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="custom-format archive created by backup_saas.py")
    parser.add_argument("--database-url", default=os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--confirm-restore", action="store_true", help="confirm replacement of the target database")
    parser.add_argument(
        "--allow-non-disposable-target",
        action="store_true",
        help="required in addition to --confirm-restore for an approved live-production recovery",
    )
    args = parser.parse_args()
    try:
        restore_backup(
            args.database_url,
            args.archive,
            confirmed=args.confirm_restore,
            allow_non_disposable_target=args.allow_non_disposable_target,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"SaaS restore failed: {exc}", file=sys.stderr)
        return 1
    print(f"SaaS restore completed: {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
