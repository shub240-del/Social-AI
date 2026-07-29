"""Latency and resource measurements against a running API.

    python tests/perf_probe.py [base_url] [--json]

Reports p50/p95/p99 per endpoint. Intended as a release gate: the budgets at
the bottom are deliberately loose enough to pass on modest hardware but tight
enough to catch an order-of-magnitude regression.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000"
for a in sys.argv[1:]:
    if not a.startswith("--"):
        BASE = a.rstrip("/")
API = f"{BASE}/api/v1"
AS_JSON = "--json" in sys.argv
PASSWORD = "Sup3rSecret-Passphrase!"

# endpoint -> p95 budget in milliseconds
BUDGETS = {
    "GET /healthz": 50,
    "GET /readyz": 150,
    "POST /auth/register": 1500,
    "POST /auth/login": 1500,
    "GET /auth/me": 150,
    "GET /workspaces": 150,
    "POST /workspaces": 250,
    "GET /brands": 150,
    "POST /chat (mock LLM)": 500,
    "GET /conversation": 150,
}


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * len(s) + 0.5)) - 1))
    return s[k]


def measure(label: str, fn, n: int = 30) -> dict:
    # Warm up so we measure steady state, not first-call import cost.
    for _ in range(3):
        fn()
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return {
        "endpoint": label,
        "n": n,
        "p50": round(statistics.median(samples), 2),
        "p95": round(pct(samples, 95), 2),
        "p99": round(pct(samples, 99), 2),
        "min": round(min(samples), 2),
        "max": round(max(samples), 2),
        "budget_p95": BUDGETS.get(label),
    }


def main() -> int:
    results: list[dict] = []
    with httpx.Client(timeout=60.0) as c:
        email = f"perf-{uuid.uuid4().hex[:10]}@example.com"
        r = c.post(
            f"{API}/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": "Perf User"},
        )
        assert r.status_code == 201, r.text
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        ws = c.get(f"{API}/auth/me", headers=h).json()["workspaces"][0]["id"]

        results.append(measure("GET /healthz", lambda: c.get(f"{BASE}/healthz")))
        results.append(measure("GET /readyz", lambda: c.get(f"{BASE}/readyz")))
        results.append(measure("GET /auth/me", lambda: c.get(f"{API}/auth/me", headers=h)))
        results.append(measure("GET /workspaces", lambda: c.get(f"{API}/workspaces", headers=h)))
        results.append(
            measure("GET /brands", lambda: c.get(f"{API}/workspaces/{ws}/brands", headers=h))
        )
        results.append(
            measure(
                "POST /workspaces",
                lambda: c.post(
                    f"{API}/workspaces",
                    headers=h,
                    json={"name": f"w{uuid.uuid4().hex[:6]}"},
                ),
                n=15,
            )
        )
        results.append(
            measure(
                "POST /auth/register",
                lambda: c.post(
                    f"{API}/auth/register",
                    json={
                        "email": f"p-{uuid.uuid4().hex[:10]}@example.com",
                        "password": PASSWORD,
                        "full_name": "P",
                    },
                ),
                n=10,
            )
        )
        results.append(
            measure(
                "POST /auth/login",
                lambda: c.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}),
                n=10,
            )
        )

        chat = c.post(f"{API}/workspaces/{ws}/chat", headers=h, json={"prompt": "hello"})
        conv = chat.json()["conversation_id"]
        results.append(
            measure(
                "POST /chat (mock LLM)",
                lambda: c.post(
                    f"{API}/workspaces/{ws}/chat",
                    headers=h,
                    json={"prompt": "Draft a short post about pricing.", "conversation_id": conv},
                ),
                n=15,
            )
        )
        results.append(
            measure(
                "GET /conversation",
                lambda: c.get(
                    f"{API}/workspaces/{ws}/chat/conversations/{conv}", headers=h
                ),
            )
        )

        # Conversation growth: latency must not blow up as history accumulates.
        big = c.post(f"{API}/workspaces/{ws}/chat", headers=h, json={"prompt": "seed"})
        bigconv = big.json()["conversation_id"]
        for i in range(20):
            c.post(
                f"{API}/workspaces/{ws}/chat",
                headers=h,
                json={"prompt": f"turn {i}", "conversation_id": bigconv},
            )
        deep = measure(
            "GET /conversation (40+ messages)",
            lambda: c.get(f"{API}/workspaces/{ws}/chat/conversations/{bigconv}", headers=h),
            n=15,
        )
        results.append(deep)

    if AS_JSON:
        print(json.dumps(results, indent=2))
        return 0

    print(f"\n{'endpoint':<34}{'p50':>9}{'p95':>9}{'p99':>9}{'budget':>9}  status")
    print("-" * 82)
    over = []
    for r in results:
        b = r["budget_p95"]
        if b is None:
            status = "-"
        elif r["p95"] <= b:
            status = "ok"
        else:
            status = "OVER"
            over.append(r)
        print(
            f"{r['endpoint']:<34}{r['p50']:>8.1f}ms{r['p95']:>8.1f}ms"
            f"{r['p99']:>8.1f}ms{(str(b) + 'ms') if b else '-':>9}  {status}"
        )
    print("-" * 82)
    if over:
        print(f"\n{len(over)} endpoint(s) exceeded the p95 budget.")
        return 1
    print("\nAll measured endpoints within budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
