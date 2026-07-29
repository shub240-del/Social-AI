"""Phase 7 - verify a deployment that actually exists.

Run this against the real URLs immediately after deploying. It asserts the
things that can only be wrong once the app is on the internet: TLS, the
production config guards having taken effect, headers surviving the proxy,
CORS matching the real frontend origin, and the database being Postgres
rather than a container-local SQLite file that vanishes on redeploy.

    python tests/post_deploy_verify.py \\
        --api https://api.socialai.io \\
        --web https://app.socialai.io

Read-only by default. `--write` additionally runs a real signup against
production, which leaves an account behind; use a disposable address.

Exit code 0 means the deployment passed. Nothing here is simulated: every
check performs a live request, and the script refuses to report success if
it could not reach the host.
"""

from __future__ import annotations

import argparse
import json
import uuid

import httpx

_passed = 0
_failed: list[str] = []
_warned: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _passed
    if ok:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed.append(f"{name} :: {detail}" if detail else name)
        print(f"  FAIL  {name}" + (f"  <- {detail}" if detail else ""))
    return ok


def warn(name: str, detail: str = "") -> None:
    _warned.append(f"{name} :: {detail}" if detail else name)
    print(f"  WARN  {name}" + (f"  <- {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def verify_api(c: httpx.Client, api: str, expect_tls: bool, expect_production: bool) -> None:
    root = api.rstrip("/")
    v1 = f"{root}/api/v1"

    section("Reachability")
    try:
        health = c.get(f"{root}/healthz")
    except httpx.RequestError as exc:
        check("API is reachable", False, f"{type(exc).__name__}: {exc}")
        return
    check("GET /healthz is 200", health.status_code == 200, f"got {health.status_code}")

    ready = c.get(f"{root}/readyz")
    check("GET /readyz is 200", ready.status_code == 200, f"got {ready.status_code}")

    section("Database")
    # /readyz touches the database, so a 200 already proves connectivity. What
    # it cannot prove is that the database is not an ephemeral SQLite file
    # inside the container, which is the failure that looks fine for a day and
    # then loses every account on the next redeploy.
    try:
        payload = ready.json()
    except json.JSONDecodeError:
        payload = {}
    db = payload.get("checks", {}).get("database", {})
    check(
        "readyz reports a healthy database",
        db.get("status") == "ok",
        f"body was {ready.text[:200]}",
    )
    dialect = db.get("dialect")
    if expect_production:
        check(
            "the database is not SQLite",
            dialect not in (None, "sqlite", "unknown"),
            f"dialect is {dialect!r} - an in-container SQLite file is lost on redeploy",
        )
    elif dialect == "sqlite":
        warn("database is SQLite", "acceptable locally, fatal in production")
    if dialect:
        print(f"        (database dialect: {dialect})")

    if expect_production:
        check(
            "readyz reports the production environment",
            payload.get("environment") == "production",
            f"got {payload.get('environment')!r} - ENVIRONMENT is not set to production",
        )
        ai = payload.get("checks", {}).get("ai", {})
        check(
            "a real AI provider is configured",
            ai.get("configured") is True,
            f"ai check says {ai} - NVIDIA_API_KEY is missing or mock is enabled",
        )

    section("Transport")
    if expect_tls:
        check("API is served over https", root.startswith("https://"), f"got {root}")
        if root.startswith("https://"):
            plain = root.replace("https://", "http://", 1)
            try:
                r = c.get(f"{plain}/healthz", follow_redirects=False)
                check(
                    "http is redirected or refused",
                    r.status_code in (301, 302, 307, 308) or r.status_code >= 400,
                    f"http returned {r.status_code} directly",
                )
            except httpx.RequestError:
                check("http is redirected or refused", True)
    else:
        warn("TLS check skipped", "running against a non-https target")

    section("Security headers")
    r = c.get(f"{root}/healthz")
    for header, expected in (
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ):
        got = r.headers.get(header)
        check(f"{header} survives the proxy", got == expected, f"got {got!r}")

    server = r.headers.get("server", "")
    check(
        "Server header does not name the stack",
        "uvicorn" not in server.lower() and "gunicorn" not in server.lower(),
        f"got {server!r}",
    )
    if expect_tls:
        hsts = r.headers.get("strict-transport-security")
        if not hsts:
            # Usually terminated at the platform edge rather than in the app.
            warn("no Strict-Transport-Security header", "confirm the platform sets it")

    section("Production hardening")
    spec = c.get(f"{v1}/openapi.json")
    if expect_production:
        check(
            "OpenAPI schema is not public",
            spec.status_code == 404,
            f"got {spec.status_code} - openapi_url should be None in production",
        )
    elif spec.status_code == 200:
        warn("OpenAPI schema is public", "expected outside production only")

    missing = c.get(f"{root}/definitely-not-a-route")
    check("unknown route is a clean 404", missing.status_code == 404, f"got {missing.status_code}")
    check("404 leaks no stack trace", "Traceback" not in missing.text)
    try:
        envelope = missing.json()
        check(
            "errors use the documented envelope",
            isinstance(envelope, dict) and "error" in envelope and "code" in envelope["error"],
            f"got {missing.text[:120]}",
        )
    except json.JSONDecodeError:
        check("errors use the documented envelope", False, "response was not JSON")

    section("Authentication is enforced")
    probe_ws = "00000000-0000-0000-0000-000000000000"
    for path in (
        "/auth/me",
        "/workspaces",
        f"/workspaces/{probe_ws}/brands",
        f"/workspaces/{probe_ws}/chat/conversations",
    ):
        r = c.get(f"{v1}{path}")
        # 401 before 404: an unauthenticated caller must not be able to learn
        # whether a workspace id exists.
        check(f"{path} rejects anonymous access", r.status_code == 401, f"got {r.status_code}")

    r = c.get(f"{v1}/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    check("a forged token is rejected", r.status_code == 401, f"got {r.status_code}")


def verify_cors(c: httpx.Client, api: str, web: str | None) -> None:
    section("CORS")
    v1 = f"{api.rstrip('/')}/api/v1"

    evil = c.options(
        f"{v1}/auth/login",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    allowed = evil.headers.get("access-control-allow-origin")
    check(
        "untrusted origin is not reflected",
        allowed != "https://evil.example.com",
        f"got {allowed!r}",
    )
    check("wildcard origin is not used", allowed != "*", f"got {allowed!r}")

    if web:
        origin = web.rstrip("/")
        good = c.options(
            f"{v1}/auth/login",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        allowed = good.headers.get("access-control-allow-origin")
        check(
            "the real frontend origin is allowed",
            allowed == origin,
            f"got {allowed!r} - ALLOWED_ORIGINS must contain {origin}",
        )


def verify_web(c: httpx.Client, web: str, api: str) -> None:
    section("Frontend")
    root = web.rstrip("/")
    try:
        r = c.get(root)
    except httpx.RequestError as exc:
        check("frontend is reachable", False, f"{type(exc).__name__}: {exc}")
        return
    check("frontend serves the homepage", r.status_code == 200, f"got {r.status_code}")
    check("homepage renders the product", "Social AI" in r.text, "marker text missing")

    for path in ("/login", "/register", "/verify", "/forgot-password", "/reset-password"):
        rp = c.get(f"{root}{path}")
        check(f"{path} is served", rp.status_code == 200, f"got {rp.status_code}")

    # A frontend still pointing at localhost is the classic broken deploy: the
    # pages render perfectly and every action fails in the browser.
    if "127.0.0.1" in r.text or "localhost:8000" in r.text:
        check(
            "frontend does not reference localhost",
            False,
            "built with the wrong NEXT_PUBLIC_API_URL",
        )
    else:
        check("frontend does not reference localhost", True)


def verify_write_path(c: httpx.Client, api: str) -> None:
    """Opt-in: prove a real user can sign up and use the product."""
    section("Live signup (creates real data)")
    v1 = f"{api.rstrip('/')}/api/v1"
    email = f"postdeploy-{uuid.uuid4().hex[:10]}@example.com"
    password = "PostDeploy-Verify-1"

    r = c.post(
        f"{v1}/auth/register",
        json={"email": email, "password": password, "full_name": "Post Deploy Check"},
    )
    ok = check(
        "registration succeeds", r.status_code == 201, f"got {r.status_code} {r.text[:160]}"
    )
    if not ok:
        return
    tokens = r.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    me = c.get(f"{v1}/auth/me", headers=headers)
    check("the new session works", me.status_code == 200, f"got {me.status_code}")
    if me.status_code != 200:
        return
    workspaces = me.json().get("workspaces", [])
    check("a starter workspace exists", len(workspaces) == 1, f"got {len(workspaces)}")

    # Repeat the call enough times to land on every replica. A token minted by
    # one process must verify on all of them.
    codes = {c.get(f"{v1}/auth/me", headers=headers).status_code for _ in range(20)}
    check("every replica accepts the token", codes == {200}, f"saw {sorted(codes)}")

    if workspaces:
        chat = c.post(
            f"{v1}/workspaces/{workspaces[0]['id']}/chat",
            headers=headers,
            json={"prompt": "Write one short launch tweet."},
        )
        if check("chat returns a completion", chat.status_code == 201, f"got {chat.status_code}"):
            text = json.dumps(chat.json()).lower()
            # The mock provider emits fixed canned text; production must not.
            check(
                "the response is not from the mock provider",
                "mock" not in text and "canned" not in text,
                "ALLOW_MOCK_LLM appears to be enabled",
            )

    login = c.post(f"{v1}/auth/login", json={"email": email, "password": password})
    check("login works for the new account", login.status_code == 200, f"got {login.status_code}")
    print(f"        (left behind account {email})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="deployed API base URL")
    parser.add_argument("--web", help="deployed frontend base URL")
    parser.add_argument("--write", action="store_true", help="also run a real signup")
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help="skip TLS assertions (for smoke-testing this script locally)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Post-deploy verification")
    print(f"  API: {args.api}")
    print(f"  Web: {args.web or '(not checked)'}")
    print("=" * 60)

    with httpx.Client(timeout=30, follow_redirects=False) as c:
        verify_api(
            c, args.api, expect_tls=not args.allow_http, expect_production=not args.allow_http
        )
        verify_cors(c, args.api, args.web)
        if args.web:
            verify_web(c, args.web, args.api)
        if args.write:
            verify_write_path(c, args.api)

    print("\n" + "=" * 60)
    print(f"  PASSED {_passed}   FAILED {len(_failed)}   WARNINGS {len(_warned)}")
    print("=" * 60)
    for f in _failed:
        print(f"  FAIL  {f}")
    for w in _warned:
        print(f"  WARN  {w}")

    if _failed:
        print("\nThe deployment is NOT verified. Do not announce it.")
        return 1
    print("\nDeployment verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
