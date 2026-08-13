from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine

from server.backfill import backfill_legacy_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy rows into one SaaS organization")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--tenant-id", required=True, help="UUID used as the organization and tenant id")
    parser.add_argument("--organization-name", default="Legacy workspace")
    parser.add_argument("--owner-email", default=None, help="Existing user to add as organization owner")
    parser.add_argument("--apply", action="store_true", help="Write changes; without this flag only show a dry run")
    args = parser.parse_args()
    report = backfill_legacy_rows(
        create_engine(args.database_url),
        tenant_id=args.tenant_id,
        organization_name=args.organization_name,
        owner_email=args.owner_email,
        apply=args.apply,
    )
    print(json.dumps({
        "tenant_id": report.tenant_id,
        "existing_tables": report.existing_tables,
        "pending_rows": report.pending_rows,
        "changed_rows": report.changed_rows,
        "applied": report.applied,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
