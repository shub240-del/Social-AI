"""The production journey, run against a live server.

Homepage -> register -> verify email -> login -> dashboard -> workspace ->
project -> AI chat -> history -> persistence -> logout -> log in again.

Unlike the unit suite this talks to a real process over real HTTP, so it also
proves the things that only break in a multi-worker deployment: a token minted
by one worker must verify on every other.

    python tests/e2e_journey.py --api http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid

import httpx

passed = 0
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global passed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed.append(f"{name} :: {detail}")
        print(f"  FAIL  {name}  <- {detail}")
    return ok


def step(title: str) -> None:
    print(f"\n--- {title} ---")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--log", help="server log file, used to recover the verification link")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    v1 = f"{api}/api/v1"
    email = f"journey-{uuid.uuid4().hex[:10]}@example.com"
    password = "JourneySecret123"

    with httpx.Client(timeout=30) as c:
        step("1. Service is up")
        health = c.get(f"{api}/healthz")
        check("GET /healthz is 200", health.status_code == 200, str(health.status_code))
        ready = c.get(f"{api}/readyz")
        check("GET /readyz reports ready", ready.json().get("status") == "ready", ready.text[:120])

        step("2. Register")
        r = c.post(
            f"{v1}/auth/register",
            json={"email": email, "password": password, "full_name": "Journey User"},
        )
        if not check("registration returns 201", r.status_code == 201, r.text[:200]):
            return 1
        tokens = r.json()
        access, refresh = tokens["access_token"], tokens["refresh_token"]
        headers = {"Authorization": f"Bearer {access}"}
        check("registration returns both tokens", bool(access and refresh))

        step("3. Verify email")
        vr = c.post(f"{v1}/auth/verify/request", json={"email": email})
        check("verification can be requested", vr.status_code == 200, vr.text[:120])
        # The log is shared by every user and both workers, so a global
        # "last token wins" scan can pick up another account's link or a
        # token that a later request already superseded. Scope the search to
        # the console-email blocks addressed to this run's mailbox.
        token = None
        if args.log:
            try:
                with open(args.log, encoding="utf-8", errors="replace") as fh:
                    blocks = fh.read().split("----- email")
                mine = [b for b in blocks if f"To:      {email}" in b]
                found = [
                    m.group(1)
                    for b in mine
                    if (m := re.search(r"/verify\?token=([A-Za-z0-9_\-]+)", b))
                ]
                token = found[-1] if found else None
            except OSError:
                token = None
        if token:
            vc = c.post(f"{v1}/auth/verify/confirm", json={"token": token})
            check("emailed link verifies the account", vc.status_code == 200, vc.text[:160])
            again = c.post(f"{v1}/auth/verify/confirm", json={"token": token})
            check("the link is single use", again.status_code == 401, str(again.status_code))
        else:
            print("  SKIP  no --log given; cannot read the emailed link")

        step("4. Login")
        login = c.post(f"{v1}/auth/login", json={"email": email, "password": password})
        if not check("login returns 200", login.status_code == 200, login.text[:200]):
            return 1
        tokens = login.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        refresh = tokens["refresh_token"]

        step("5. Dashboard")
        me = c.get(f"{v1}/auth/me", headers=headers)
        check("GET /auth/me is 200", me.status_code == 200, me.text[:160])
        workspaces = me.json().get("workspaces", [])
        check("a starter workspace exists", len(workspaces) == 1, f"got {len(workspaces)}")
        codes = {c.get(f"{v1}/auth/me", headers=headers).status_code for _ in range(20)}
        check("every worker accepts the token", codes == {200}, f"saw {sorted(codes)}")

        if not workspaces:
            return 1
        ws = workspaces[0]["id"]

        step("6. Workspace")
        listed = c.get(f"{v1}/workspaces", headers=headers)
        check("workspaces are listed", listed.status_code == 200, str(listed.status_code))
        brands = c.get(f"{v1}/workspaces/{ws}/brands", headers=headers)
        check("a default brand exists", len(brands.json()) == 1, brands.text[:120])
        brand_id = brands.json()[0]["id"]

        step("7. Project (campaign)")
        campaign = c.post(
            f"{v1}/workspaces/{ws}/campaigns",
            headers=headers,
            json={"name": "Spring launch", "objective": "Drive signups", "brand_id": brand_id},
        )
        check("a campaign can be created", campaign.status_code == 201, campaign.text[:200])
        campaign_id = campaign.json()["id"] if campaign.status_code == 201 else None

        step("8. AI chat")
        chat = c.post(
            f"{v1}/workspaces/{ws}/chat",
            headers=headers,
            json={
                "prompt": "Write one short launch tweet for our espresso blend.",
                "brand_id": brand_id,
                "campaign_id": campaign_id,
            },
        )
        if not check("chat returns 201", chat.status_code == 201, chat.text[:200]):
            return 1
        result = chat.json()
        conversation_id = result["conversation_id"]
        check("the assistant replied with text", bool(result["message"]["content"]))

        follow = c.post(
            f"{v1}/workspaces/{ws}/chat",
            headers=headers,
            json={"prompt": "Now make it shorter.", "conversation_id": conversation_id},
        )
        check("a follow-up stays in the conversation",
              follow.status_code == 201
              and follow.json()["conversation_id"] == conversation_id,
              follow.text[:160])

        step("9. Conversation history")
        detail = c.get(f"{v1}/workspaces/{ws}/chat/conversations/{conversation_id}", headers=headers)
        messages = detail.json().get("messages", [])
        check("all four turns are stored", len(messages) == 4, f"got {len(messages)}")
        check("turns are correctly ordered",
              [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"],
              str([m["role"] for m in messages]))

        step("10. Persistence across a new session")
        relogin = c.post(f"{v1}/auth/login", json={"email": email, "password": password})
        fresh = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
        history = c.get(f"{v1}/workspaces/{ws}/chat/conversations", headers=fresh)
        check("history survives a new login",
              any(x["id"] == conversation_id for x in history.json()),
              history.text[:160])

        step("11. Logout")
        out = c.post(f"{v1}/auth/logout", headers=headers, json={"refresh_token": refresh})
        check("logout returns 200", out.status_code == 200, out.text[:120])
        dead = c.post(f"{v1}/auth/refresh", json={"refresh_token": refresh})
        check("the old session cannot refresh", dead.status_code == 401, str(dead.status_code))

        step("12. Log in again")
        final = c.post(f"{v1}/auth/login", json={"email": email, "password": password})
        check("login works after logout", final.status_code == 200, final.text[:160])
        final_headers = {"Authorization": f"Bearer {final.json()['access_token']}"}
        still = c.get(f"{v1}/workspaces/{ws}/chat/conversations/{conversation_id}",
                      headers=final_headers)
        check("the conversation is still readable", still.status_code == 200, str(still.status_code))

    print("\n" + "=" * 56)
    print(f"  PASSED {passed}   FAILED {len(failed)}")
    print("=" * 56)
    for f in failed:
        print(f"  FAIL  {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
