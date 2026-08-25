# Production release runbook

This Compose stack is safe to use as a production baseline only after it is
configured with real secrets and an HTTPS domain. The API, PostgreSQL, Redis,
and MinIO management ports bind to `127.0.0.1` by default; the optional Caddy
profile is the only public entry point.

## 1. Prepare the host

- Use a supported Linux host with Docker Compose v2.
- Point the DNS A/AAAA record for the application domain to the host.
- Allow inbound TCP 80 and 443 only. Do not expose 5432, 6379, 9000, or 9001.
- Copy `.env.example` to `.env` and keep it outside source control.
- Keep Caddy as the only public API entry point. Its reverse proxy ignores
  untrusted client-supplied forwarding headers before the API derives
  rate-limit keys.
- Collect the structured Caddy access-log stream with your deployment
  platform and configure retention/alerts there; application secrets are never
  logged by the API.

## 2. Set production values

At minimum, set the following values in `.env`:

```dotenv
APP_ENV=production
TZ=Asia/Shanghai
SECRET_KEY=<a unique random value of at least 32 characters>
POSTGRES_PASSWORD=<unique migration-owner password>
APP_DB_PASSWORD=<unique runtime-role password>
REDIS_PASSWORD=<unique URL-safe password of at least 16 characters>
OBJECT_STORAGE_ACCESS_KEY=<unique access key>
OBJECT_STORAGE_SECRET_KEY=<unique secret>
CORS_ORIGINS=https://learn.example.com
DEPLOYMENT_DOMAIN=learn.example.com
CADDY_ACME_EMAIL=ops@example.com
```

Set the AI provider keys only for the features you intend to enable. Keep
`LEARNING_AI_ENABLED=false` until a valid provider key and spending limits are
configured. Never reuse the migration-owner password for `APP_DB_PASSWORD`.

## 3. Deploy and verify

```powershell
python scripts/validate_production_env.py --env-file .env
docker compose -f docker-compose.saas.yml --profile production up -d --build
docker compose -f docker-compose.saas.yml run --rm migrate python scripts/verify_saas_integration.py
python scripts/verify_http_security.py --base-url https://learn.example.com
python scripts/smoke_test_saas.py --base-url https://learn.example.com
```

Then verify `https://learn.example.com/health/ready` and
`https://learn.example.com/web/` from a separate network. The verification
script checks pgvector, the HNSW index, tenant `NOT NULL` constraints, RLS, and
that the API runtime role is not privileged. The smoke test creates a uniquely
named disposable workspace and exercises registration, course/goal/task setup,
knowledge linking, course-note CRUD, practice attempts, mistake capture, All
Time analytics, reminders, and task completion. Run it only against a
disposable staging database or a fresh deployment.

`verify_http_security.py` verifies the public Web shell has a restrictive CSP,
anti-framing, anti-content-sniffing and referrer policies; that authenticated
API responses are not cacheable; and, for HTTPS URLs, that HSTS is enabled.

The current migration head is `g16_course_notes`. After every release,
confirm the running database reports the same head:

```powershell
docker compose -f docker-compose.saas.yml run --rm migrate python -m alembic current
```

The default SaaS stack disables the Web Coding Agent and does not mount the
host Docker socket. Keep that setting for public deployments. If a trusted,
admin-only environment explicitly needs generated code execution, use the
optional override and review the network boundary first:

```powershell
docker compose -f docker-compose.saas.yml -f docker-compose.coding.yml --profile production up -d --build
```

This override grants the API container access to `/var/run/docker.sock`; do
not use it for an internet-facing multi-tenant deployment without an
additional isolated runner service.

Take a database backup before applying migrations and retain a tested restore
copy. For a PostgreSQL backup, run `pg_dump` from a trusted host with the
migration-owner credentials; never use the restricted runtime role for backups.
The repository also provides a non-overwriting backup helper that verifies the
custom-format archive with `pg_restore --list`. The SaaS image pins a
PostgreSQL 16 client to match the `pgvector:pg16` database, so use the pinned
migration runtime rather than relying on a potentially incompatible host tool:

```powershell
$env:MIGRATION_DATABASE_URL="postgresql+psycopg://learning:<owner-password>@postgres:5432/learning"
docker compose -f docker-compose.saas.yml run --rm -e MIGRATION_DATABASE_URL migrate python scripts/backup_saas.py --output backups/learning-pre-release.dump
```

Restore only into a disposable database during a scheduled recovery drill;
never restore over the live database as part of a normal release. The restore
helper validates the archive first and refuses a non-disposable database name
unless the operator explicitly opts into an approved emergency recovery:

```powershell
$env:MIGRATION_DATABASE_URL="postgresql+psycopg://learning:<owner-password>@postgres:5432/learning_recovery_drill"
docker compose -f docker-compose.saas.yml run --rm -e MIGRATION_DATABASE_URL migrate python scripts/restore_saas.py backups/learning-pre-release.dump --confirm-restore
```

Verify the restored database with `scripts/verify_saas_integration.py` before
recording the recovery drill. `--allow-non-disposable-target` is deliberately
required in addition to `--confirm-restore` for a live-production recovery.

## 4. Release gates

- Create a restore-tested PostgreSQL backup and retain object storage backups.
- Confirm rate limits and CORS use the production domain.
- Run `python scripts/verify_http_security.py --base-url https://<your-domain>`.
- Review worker/API logs after creating a test organization, resource, and
  knowledge-draft review.
- Use a trusted Windows code-signing certificate before shipping the desktop
  package: `python scripts/build_windows.py --require-signature`.
- Keep the generated `release-manifest.json` inside the package and the
  adjacent `.zip.sha256` file with the release record; verify both before
  publishing the download.
- Keep the signing certificate, `.env`, and any AI API key in a secret manager;
  none belong in Git or a distributable ZIP.
