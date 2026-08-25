"""Verify browser-facing security headers for a deployed Learning Space API."""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def fetch(url: str) -> tuple[int, dict[str, str]]:
    request = Request(url, headers={"User-Agent": "learning-space-release-check/1.0"})
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - caller supplies the release URL.
            return response.status, dict(response.headers.items())
    except HTTPError as error:
        return error.code, dict(error.headers.items())


def header(headers: dict[str, str], name: str) -> str:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), "")


def verify(base_url: str) -> dict[str, object]:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be an absolute HTTP(S) URL")
    root = base_url.rstrip("/")
    web_status, web_headers = fetch(f"{root}/web/")
    api_status, api_headers = fetch(f"{root}/v1/me")
    errors: list[str] = []
    if web_status != 200:
        errors.append(f"/web/ returned {web_status}, expected 200")
    required_web_headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }
    for name, expected in required_web_headers.items():
        if header(web_headers, name) != expected:
            errors.append(f"/web/ {name} must be {expected!r}")
    policy = header(web_headers, "Content-Security-Policy")
    for directive in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "script-src 'self'"):
        if directive not in policy:
            errors.append(f"/web/ Content-Security-Policy is missing {directive!r}")
    if "script-src 'self' 'unsafe-inline'" in policy:
        errors.append("/web/ Content-Security-Policy must not allow inline scripts")
    if api_status != 401:
        errors.append(f"/v1/me returned {api_status}, expected unauthenticated 401")
    if header(api_headers, "Cache-Control") != "no-store":
        errors.append("/v1/me Cache-Control must be 'no-store'")
    if parsed.scheme == "https" and "max-age=" not in header(web_headers, "Strict-Transport-Security"):
        errors.append("HTTPS deployment is missing Strict-Transport-Security")
    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "status": "passed",
        "base_url": root,
        "web_status": web_status,
        "api_status": api_status,
        "hsts_checked": parsed.scheme == "https",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.base_url), ensure_ascii=False))
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"status": "failed", "detail": str(error)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
