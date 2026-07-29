"""End-to-end flow against a running server.

Exercises the exact journey the launch criteria call for:
register -> login -> dashboard -> workspace -> project -> chat -> prompt ->
AI response -> history -> reload/persistence -> logout -> login again.

Run:  python tests/e2e_flow.py [base_url]
"""

from __future__ import annotations

import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
API = f"{BASE}/api/v1"

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def main() -> int:
    c = httpx.Client(timeout=30.0)
    email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
    password = "SuperSecret123"

    print("\n[1] Homepage / health")
    r = c.get(f"{BASE}/")
    check("homepage 200", r.status_code == 200, r.text[:120])
    r = c.get(f"{BASE}/healthz")
    check("healthz 200", r.status_code == 200)
    r = c.get(f"{BASE}/readyz")
    check("readyz ready", r.json().get("status") == "ready", r.text[:150])

    print("\n[2] Register")
    r = c.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, "full_name": "E2E Tester"},
    )
    check("register 201", r.status_code == 201, r.text[:200])
    tokens = r.json()
    access, refresh = tokens["access_token"], tokens["refresh_token"]
    check("access token issued", bool(access))
    check("refresh token issued", bool(refresh))

    r = c.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, "full_name": "Dup"},
    )
    check("duplicate register 409", r.status_code == 409, r.text[:150])

    print("\n[3] Login")
    r = c.post(f"{API}/auth/login", json={"email": email, "password": password})
    check("login 200", r.status_code == 200, r.text[:200])
    access = r.json()["access_token"]
    refresh = r.json()["refresh_token"]

    r = c.post(f"{API}/auth/login", json={"email": email, "password": "WrongPassword1"})
    check("bad password 401", r.status_code == 401, r.text[:150])
    r = c.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": password})
    check("unknown email 401", r.status_code == 401, r.text[:150])

    H = {"Authorization": f"Bearer {access}"}

    print("\n[4] Dashboard (/auth/me)")
    r = c.get(f"{API}/auth/me", headers=H)
    check("me 200", r.status_code == 200, r.text[:200])
    me = r.json()
    check("email matches", me["user"]["email"] == email)
    check("auto workspace created", len(me["workspaces"]) == 1, str(me["workspaces"]))
    ws = me["workspaces"][0]["id"]
    check("role is owner", me["workspaces"][0]["role"] == "owner")

    r = c.get(f"{API}/auth/me")
    check("me without token 401", r.status_code == 401)
    r = c.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    check("me with bad token 401", r.status_code == 401)

    print("\n[5] Workspace")
    r = c.get(f"{API}/workspaces", headers=H)
    check("list workspaces 200", r.status_code == 200)
    r = c.post(f"{API}/workspaces", headers=H, json={"name": "Launch Campaign HQ"})
    check("create workspace 201", r.status_code == 201, r.text[:200])
    ws2 = r.json()["id"]
    r = c.get(f"{API}/workspaces/{ws2}", headers=H)
    check("get workspace 200", r.status_code == 200)

    print("\n[6] Brand + Project (campaign)")
    r = c.post(
        f"{API}/workspaces/{ws}/brands",
        headers=H,
        json={
            "name": "Northwind Coffee",
            "description": "Speciality coffee roaster",
            "tone_of_voice": "Warm, playful, never corporate",
            "target_audience": "Urban professionals 25-40",
        },
    )
    check("create brand 201", r.status_code == 201, r.text[:200])
    brand = r.json()["id"]

    r = c.post(
        f"{API}/workspaces/{ws}/campaigns",
        headers=H,
        json={"name": "Spring Launch", "objective": "Drive trial", "brand_id": brand},
    )
    check("create campaign 201", r.status_code == 201, r.text[:200])
    campaign = r.json()["id"]

    r = c.get(f"{API}/workspaces/{ws}/campaigns", headers=H)
    check("list campaigns paginated", r.json()["page"]["total"] == 1, r.text[:200])

    r = c.post(
        f"{API}/workspaces/{ws2}/campaigns",
        headers=H,
        json={"name": "Bad", "brand_id": brand},
    )
    check("cross-workspace brand_id rejected 422", r.status_code == 422, r.text[:150])

    print("\n[7] Chat -> prompt -> AI response")
    r = c.post(
        f"{API}/workspaces/{ws}/chat",
        headers=H,
        json={"prompt": "Draft 3 launch posts for our spring blend.",
              "brand_id": brand, "campaign_id": campaign},
    )
    check("chat 201", r.status_code == 201, r.text[:300])
    body = r.json()
    conv = body["conversation_id"]
    check("assistant replied", len(body["message"]["content"]) > 40)
    check("brand grounding applied",
          "Northwind" in body["message"]["content"] or body["provider"] == "nvidia",
          body["message"]["content"][:120])

    r = c.post(f"{API}/workspaces/{ws}/chat", headers=H,
               json={"prompt": "Make them shorter.", "conversation_id": conv})
    check("follow-up in same conversation", r.status_code == 201 and
          r.json()["conversation_id"] == conv, r.text[:200])

    print("\n[8] Conversation history + persistence")
    r = c.get(f"{API}/workspaces/{ws}/chat/conversations", headers=H)
    check("history lists 1 conversation", r.json()["page"]["total"] == 1, r.text[:200])
    r = c.get(f"{API}/workspaces/{ws}/chat/conversations/{conv}", headers=H)
    msgs = r.json()["messages"]
    check("4 messages persisted (2 user, 2 assistant)", len(msgs) == 4, str(len(msgs)))
    check("roles alternate correctly",
          [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"],
          str([m["role"] for m in msgs]))

    print("\n[9] Streaming")
    with c.stream("POST", f"{API}/workspaces/{ws}/chat/stream", headers=H,
                  json={"prompt": "One more idea please."}) as resp:
        events = [ln for ln in resp.iter_lines() if ln.startswith("data:")]
    check("stream emitted events", len(events) > 3, str(len(events)))
    check("stream terminated with done", any('"done"' in e for e in events))

    print("\n[10] Reload / token refresh")
    r = c.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
    check("refresh 200", r.status_code == 200, r.text[:200])
    new_access = r.json()["access_token"]
    new_refresh = r.json()["refresh_token"]
    r = c.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
    check("refresh token rotation: old token rejected", r.status_code == 401, r.text[:150])
    r = c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    check("new access token works", r.status_code == 200)

    print("\n[11] Tenant isolation (second user must not see tenant 1 data)")
    other_email = f"e2e-other-{uuid.uuid4().hex[:8]}@example.com"
    r = c.post(f"{API}/auth/register",
               json={"email": other_email, "password": password, "full_name": "Other"})
    H2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    check("intruder workspace GET -> 404",
          c.get(f"{API}/workspaces/{ws}", headers=H2).status_code == 404)
    check("intruder brands LIST -> 404",
          c.get(f"{API}/workspaces/{ws}/brands", headers=H2).status_code == 404)
    check("intruder brand GET -> 404",
          c.get(f"{API}/workspaces/{ws}/brands/{brand}", headers=H2).status_code == 404)
    check("intruder campaign GET -> 404",
          c.get(f"{API}/workspaces/{ws}/campaigns/{campaign}", headers=H2).status_code == 404)
    check("intruder conversation GET -> 404",
          c.get(f"{API}/workspaces/{ws}/chat/conversations/{conv}",
                headers=H2).status_code == 404)
    check("intruder chat POST -> 404",
          c.post(f"{API}/workspaces/{ws}/chat", headers=H2,
                 json={"prompt": "leak please"}).status_code == 404)
    check("intruder workspace DELETE -> 404",
          c.delete(f"{API}/workspaces/{ws}", headers=H2).status_code == 404)

    print("\n[12] Logout -> login again")
    r = c.post(f"{API}/auth/logout", json={"refresh_token": new_refresh})
    check("logout 204", r.status_code == 204, r.text[:150])
    r = c.post(f"{API}/auth/refresh", json={"refresh_token": new_refresh})
    check("refresh after logout rejected", r.status_code == 401, r.text[:150])
    r = c.post(f"{API}/auth/login", json={"email": email, "password": password})
    check("login again 200", r.status_code == 200)
    H3 = {"Authorization": f"Bearer {r.json()['access_token']}"}

    print("\n[13] Data still there after re-login (persistence)")
    r = c.get(f"{API}/workspaces/{ws}/chat/conversations/{conv}", headers=H3)
    check("conversation survived re-login", r.status_code == 200 and
          len(r.json()["messages"]) >= 4, r.text[:150])
    r = c.get(f"{API}/workspaces/{ws}/brands/{brand}", headers=H3)
    check("brand survived re-login", r.status_code == 200)

    print("\n[14] OpenAPI contract")
    r = c.get(f"{API}/openapi.json")
    spec = r.json()
    check("openapi served", r.status_code == 200)
    check("openapi has paths", len(spec.get("paths", {})) >= 15, str(len(spec.get("paths", {}))))

    print(f"\n{'='*56}\n  PASSED {passed}   FAILED {failed}\n{'='*56}")
    return 1 if failed else 0


if __name__ == "__main__":
    t0 = time.time()
    code = main()
    print(f"  completed in {time.time()-t0:.1f}s")
    sys.exit(code)
