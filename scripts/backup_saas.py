"""Create and verify a PostgreSQL custom-format backup for the SaaS stack.

The script never overwrites an existing backup unless ``--force`` is passed.
It validates the resulting archive with ``pg_restore --list`` so a successful
exit means the artifact is readable, not merely that pg_dump started.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

try:  # Supports both ``python scripts/backup_saas.py`` and module imports in tests.
    from scripts.postgres_urls import postgres_client_url
except ModuleNotFoundError:  # pragma: no cover - exercised by the Compose runtime.
    from postgres_urls import postgres_client_url


def create_backup(database_url: str, output: Path, *, force: bool = False) -> Path:
    client_url = postgres_client_url(database_url)
    if output.exists() and not force:
        raise FileExistsError(f"backup already exists: {output}; pass --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                "--dbname", client_url, "--file", str(output),
            ],
            check=True,
        )
        subprocess.run(["pg_restore", "--list", str(output)], check=True, capture_output=True, text=True)
    except Exception:
        if output.is_file():
            output.unlink()
        raise
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", ""))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backups") / f"learning-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.dump",
    )
    parser.add_argument("--force", action="store_true", help="replace an existing output archive")
    args = parser.parse_args()
    try:
        result = create_backup(args.database_url, args.output, force=args.force)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"SaaS backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"SaaS backup created and verified: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
