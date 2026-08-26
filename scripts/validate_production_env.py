"""Validate the non-secret shape of a production SaaS environment file.

The command intentionally reports field names and remediation hints only; it
never prints secret values. It is safe to run in CI and on a deployment host.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlparse


PLACEHOLDER_MARKERS = ("change-me", "replace-with", "development-only", "example-password")


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"line {line_number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"line {line_number} has an invalid environment key")
        values[key] = value.strip().strip('"').strip("'")
    return values


def _placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if values.get("APP_ENV", "").lower() not in {"production", "prod"}:
        errors.append("APP_ENV must be production")

    for key, minimum in (("SECRET_KEY", 32), ("REDIS_PASSWORD", 16)):
        value = values.get(key, "")
        if len(value) < minimum or _placeholder(value):
            errors.append(f"{key} must be a non-placeholder random value of at least {minimum} characters")

    for key in ("POSTGRES_PASSWORD", "APP_DB_PASSWORD", "OBJECT_STORAGE_ACCESS_KEY", "OBJECT_STORAGE_SECRET_KEY"):
        if _placeholder(values.get(key, "")):
            errors.append(f"{key} must be configured with a non-placeholder value")
    if values.get("POSTGRES_PASSWORD") == values.get("APP_DB_PASSWORD"):
        errors.append("POSTGRES_PASSWORD and APP_DB_PASSWORD must be different")

    database_url = values.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql") or _placeholder(database_url):
        errors.append("DATABASE_URL must be a non-placeholder PostgreSQL URL")

    redis_password = values.get("REDIS_PASSWORD", "")
    if redis_password and not re.fullmatch(r"[A-Za-z0-9._~-]+", redis_password):
        errors.append("REDIS_PASSWORD must be URL-safe")
    redis_url = values.get("REDIS_URL", "")
    parsed_redis = urlparse(redis_url)
    if not parsed_redis.password or unquote(parsed_redis.password) != redis_password:
        errors.append("REDIS_URL must contain the same password as REDIS_PASSWORD")

    cors = values.get("CORS_ORIGINS", "")
    if not cors or "*" in cors or any(origin.strip().startswith(("http://localhost", "http://127.0.0.1")) for origin in cors.split(",")):
        errors.append("CORS_ORIGINS must list explicit public HTTPS origins")
    elif any(not origin.strip().startswith("https://") for origin in cors.split(",")):
        errors.append("CORS_ORIGINS must use HTTPS origins in production")
    if not values.get("DEPLOYMENT_DOMAIN", "").strip() or not values.get("CADDY_ACME_EMAIL", "").strip():
        errors.append("DEPLOYMENT_DOMAIN and CADDY_ACME_EMAIL are required for the HTTPS entry point")
    if values.get("PUBLIC_REGISTRATION_ENABLED", "true").lower() not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        errors.append("PUBLIC_REGISTRATION_ENABLED must be a boolean")

    if values.get("LEARNING_AI_ENABLED", "false").lower() in {"1", "true", "yes", "on"} and _placeholder(values.get("LEARNING_AI_API_KEY", "")):
        errors.append("LEARNING_AI_API_KEY is required when LEARNING_AI_ENABLED is true")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    if not args.env_file.is_file():
        print(f"environment file not found: {args.env_file}", file=sys.stderr)
        return 2
    try:
        errors = validate(parse_env_file(args.env_file))
    except (OSError, ValueError) as exc:
        print(f"could not parse environment file: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("Production environment validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Production environment validated: {args.env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
