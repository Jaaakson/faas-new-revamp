"""Post-deploy smoke test.

Gates a release. If this fails, the deploy rolls back.

It exercises the **product**, not the process. Checking that `/health` returns
200 proves a process is listening; it does not prove the models loaded, the
database migrated, the tenant filter works, or that a face can actually be
verified. Every one of those has broken in this codebase at least once while
`/health` stayed green, so each is a check here.

    python scripts/smoke_test.py --base https://api.fvas.io

Read-only where it can be, and where it cannot, it cleans up after itself. A
smoke test that leaves debris in production is a smoke test people disable.
"""

from __future__ import annotations

import argparse
import base64
import struct
import sys
import time
from dataclasses import dataclass, field

import httpx

MAGIC = b"FVASFAKE"
HEADER = struct.Struct("<8sI5fI")


def synthetic_frame(identity: int, seed: int = 0) -> str:
    payload = bytearray(HEADER.pack(MAGIC, identity, 0.9, 0.5, 0.0, 0.0, 0.0, 1))
    payload += b"\x00" * (2048 - len(payload))
    if seed:
        payload[-4:] = seed.to_bytes(4, "little")
    return base64.b64encode(bytes(payload)).decode()


class SmokeCheckError(Exception):
    """A failed check. Distinct from an unexpected crash, which is also a failure."""


def require(condition: object, message: str) -> None:
    """Assert-shaped, but real.

    The built-in assert statement would be the natural idiom here and is the
    wrong one: `python -O` removes those statements entirely, and a smoke test
    that silently passes everything under an optimisation flag is worse than no
    smoke test at all.
    """
    if not condition:
        raise SmokeCheckError(message)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    duration_ms: int = 0


@dataclass
class Smoke:
    checks: list[Check] = field(default_factory=list)

    def run(self, name: str, fn) -> bool:  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        try:
            detail = fn() or ""
            passed = True
        except SmokeCheckError as exc:
            detail, passed = str(exc), False
        except Exception as exc:
            detail, passed = f"{type(exc).__name__}: {exc}", False

        self.checks.append(
            Check(name, passed, str(detail), int((time.perf_counter() - started) * 1000))
        )
        return passed

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.checks)

    def report(self) -> None:
        print()
        for check in self.checks:
            mark = "PASS" if check.passed else "FAIL"
            print(f"  {mark}  {check.name:44} {check.duration_ms:>5} ms  {check.detail}")
        failed = [c for c in self.checks if not c.passed]
        print()
        print(f"  {len(self.checks) - len(failed)}/{len(self.checks)} checks passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--web", default="http://localhost:3000")
    parser.add_argument("--email", default="owner@acme.example.com")
    parser.add_argument("--password", default="Password123!demo")
    parser.add_argument(
        "--expect-engine",
        default=None,
        help="fail unless the deployed engine matches (use `insightface` in production)",
    )
    args = parser.parse_args()

    # Windows consoles default to cp1252 and raise on any non-ASCII output.
    # A smoke test that crashes on the terminal it is run from is worse than
    # useless, so force UTF-8 and degrade rather than fail.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    smoke = Smoke()
    client = httpx.Client(timeout=30.0)
    state: dict[str, str] = {}

    # ── Liveness and configuration ────────────────────────────────────────────

    def health() -> str:
        response = client.get(f"{args.base}/health")
        require(response.status_code == 200, f"health returned {response.status_code}")
        body = response.json()
        state["engine"] = body["face_engine"]
        if args.expect_engine:
            require(
                body["face_engine"] == args.expect_engine,
                f"engine is {body['face_engine']}, expected {args.expect_engine}",
            )
        return f"v{body['version']} | {body['environment']} | engine={body['face_engine']}"

    def readiness() -> str:
        response = client.get(f"{args.base}/ready")
        require(
            response.status_code == 200,
            f"not ready: {response.status_code} {response.text}",
        )
        return "dependencies reachable"

    def security_headers() -> str:
        response = client.get(f"{args.base}/health")
        required = {
            "x-content-type-options": "nosniff",
            "x-frame-options": None,
            "referrer-policy": None,
            "content-security-policy": None,
        }
        missing = [h for h in required if h not in response.headers]
        require(not missing, f"missing headers: {', '.join(missing)}")
        require(response.headers["x-content-type-options"] == "nosniff", "unexpected response")
        return f"{len(required)} present"

    def docs_hidden_in_production() -> str:
        # A production deploy must not publish its own interactive docs.
        response = client.get(f"{args.base}/health")
        environment = response.json()["environment"]
        docs = client.get(f"{args.base}/docs")
        if environment == "production":
            require(docs.status_code == 404, "interactive docs are exposed in production")
            return "hidden (production)"
        return f"exposed ({environment}) - correct outside production"

    # ── The product loop ──────────────────────────────────────────────────────

    def login() -> str:
        response = client.post(
            f"{args.base}/v1/console/auth/login",
            json={"email": args.email, "password": args.password},
        )
        require(response.status_code == 200, f"login failed: {response.status_code}")
        state["jwt"] = response.json()["access_token"]
        return "console session established"

    def mint_key() -> str:
        response = client.post(
            f"{args.base}/v1/console/api-keys",
            json={"name": "smoke-test", "environment": "test"},
            headers={"Authorization": f"Bearer {state['jwt']}"},
        )
        require(response.status_code == 201, f"key creation failed: {response.text[:200]}")
        body = response.json()
        state["key"] = body["secret"]
        state["key_id"] = body["id"]
        return f"{body['key_prefix']}..."

    def public_api_loop() -> str:
        auth = {"Authorization": f"Bearer {state['key']}"}
        identity = int(time.time()) % 90_000 + 5_000

        subject = client.post(
            f"{args.base}/v1/subjects",
            json={"external_id": f"smoke_{int(time.time())}"},
            headers=auth,
        )
        require(subject.status_code == 201, f"create subject: {subject.text[:200]}")
        state["subject_id"] = subject.json()["id"]

        enrolled = client.post(
            f"{args.base}/v1/enrollments",
            json={
                "subject_id": state["subject_id"],
                "images": [synthetic_frame(identity, i + 1) for i in range(3)],
            },
            headers=auth,
        )
        require(enrolled.status_code == 201, f"enroll: {enrolled.text[:200]}")

        verified = client.post(
            f"{args.base}/v1/verifications",
            json={"subject_id": state["subject_id"], "image": synthetic_frame(identity, 99)},
            headers=auth,
        )
        require(verified.status_code == 200, f"verify: {verified.text[:200]}")
        decision = verified.json()["decision"]
        require(decision == "verified", f"expected verified, got {decision}")

        return f"create -> enroll -> verify ({verified.json()['similarity']:.4f})"

    def wrong_face_is_rejected() -> str:
        """The check that proves matching is real rather than always-yes."""
        auth = {"Authorization": f"Bearer {state['key']}"}
        response = client.post(
            f"{args.base}/v1/verifications",
            json={"subject_id": state["subject_id"], "image": synthetic_frame(777_777, 5)},
            headers=auth,
        )
        require(response.status_code == 200, "unexpected response")
        decision = response.json()["decision"]
        require(decision == "rejected", f"a different face returned {decision}, not rejected")
        return "a different face is rejected"

    def unauthenticated_is_refused() -> str:
        response = client.post(f"{args.base}/v1/subjects", json={"external_id": "nope"})
        require(
            response.status_code == 401,
            f"unauthenticated request returned {response.status_code}",
        )
        return "401 without a key"

    def revocation_is_immediate() -> str:
        client.delete(
            f"{args.base}/v1/console/api-keys/{state['key_id']}",
            headers={"Authorization": f"Bearer {state['jwt']}"},
        )
        response = client.get(
            f"{args.base}/v1/subjects?limit=1", headers={"Authorization": f"Bearer {state['key']}"}
        )
        require(response.status_code == 401, f"revoked key still works: {response.status_code}")
        return "revoked key stops working on the next request"

    def cleanup() -> str:
        # Leave nothing behind. A smoke test that litters production is one
        # that gets switched off.
        client.delete(
            f"{args.base}/v1/console/subjects/{state['subject_id']}",
            headers={"Authorization": f"Bearer {state['jwt']}"},
        )
        return "test subject and key removed"

    def web_reachable() -> str:
        response = client.get(f"{args.web}/login", follow_redirects=True)
        require(response.status_code == 200, f"web returned {response.status_code}")
        return "login page served"

    checks = [
        ("liveness", health),
        ("readiness (database, redis)", readiness),
        ("security headers", security_headers),
        ("interactive docs exposure", docs_hidden_in_production),
        ("console login", login),
        ("api key creation", mint_key),
        ("public api: create, enroll, verify", public_api_loop),
        ("matching actually discriminates", wrong_face_is_rejected),
        ("unauthenticated requests refused", unauthenticated_is_refused),
        ("key revocation is immediate", revocation_is_immediate),
        ("cleanup", cleanup),
        ("web app reachable", web_reachable),
    ]

    print(f"\nsmoke test → {args.base}")
    for name, fn in checks:
        if not smoke.run(name, fn) and name in {"liveness", "console login"}:
            # Nothing downstream can pass without these; stop rather than
            # printing a cascade of failures that all have one cause.
            break

    smoke.report()
    client.close()

    if not smoke.ok:
        print("\n  SMOKE TEST FAILED — this deploy should be rolled back.\n")
        return 1

    print("\n  All checks passed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
