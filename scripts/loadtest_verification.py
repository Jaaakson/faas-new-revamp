"""Sustained load against POST /v1/verifications.

Measures what the endpoint does, not what it should do. Everything reported here
is observed; nothing is projected.

    uv run python scripts/loadtest_verification.py --requests 300 --concurrency 8

Two honesty constraints shape the design:

* **Percentiles are computed from the full sample**, not from a running
  approximation. At a few hundred requests there is no reason to estimate.
* **The engine under test is named in the output.** A p95 measured against
  `FakeFaceEngine` says something about the *framework* — routing, auth, quota,
  the database round trips — and nothing about ONNX inference. Reporting the two
  as if they were the same number would be the single most misleading thing this
  script could do, so it prints which one ran and adds the Phase 0 measurement
  for the stage it is not exercising.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import statistics
import struct
import sys
import time
from dataclasses import dataclass, field

import httpx

MAGIC = b"FVASFAKE"
HEADER = struct.Struct("<8sI5fI")


def frame(identity: int = 1, seed: int = 0) -> str:
    payload = bytearray(HEADER.pack(MAGIC, identity, 0.9, 0.5, 0.0, 0.0, 0.0, 1))
    payload += b"\x00" * (2048 - len(payload))
    if seed:
        payload[-4:] = seed.to_bytes(4, "little")
    return base64.b64encode(bytes(payload)).decode()


@dataclass
class Results:
    latencies_ms: list[float] = field(default_factory=list)
    decisions: dict[str, int] = field(default_factory=dict)
    statuses: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record(self, status: int, elapsed_ms: float, body: dict | None) -> None:
        self.statuses[status] = self.statuses.get(status, 0) + 1
        # Only successful calls contribute to the latency profile. Including a
        # fast 429 would flatter the numbers by counting work that never ran.
        if status == 200 and body:
            self.latencies_ms.append(elapsed_ms)
            decision = str(body.get("decision"))
            self.decisions[decision] = self.decisions.get(decision, 0) + 1


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank. Exact for the sample, with no interpolation to argue about."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]


async def setup(
    client: httpx.AsyncClient, base: str, email: str, password: str
) -> tuple[str, str, int]:
    """Log in, mint a key, enroll a subject.

    Returns (api_key, subject_id, identity).
    """
    login = await client.post(
        f"{base}/v1/console/auth/login", json={"email": email, "password": password}
    )
    login.raise_for_status()
    jwt = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {jwt}"}

    key = await client.post(
        f"{base}/v1/console/api-keys",
        json={"name": "loadtest", "environment": "test"},
        headers=headers,
    )
    if key.status_code != 201:
        raise SystemExit(f"could not mint a key: {key.status_code} {key.text}")
    secret = key.json()["secret"]

    api = {"Authorization": f"Bearer {secret}"}
    # A fresh synthetic identity per run. Reusing one would collide with a
    # previous run's profile and fail duplicate detection before a single
    # measurement was taken.
    identity = int(time.time()) % 100_000 + 10_000
    external_id = f"loadtest_{int(time.time())}"
    subject = await client.post(
        f"{base}/v1/subjects", json={"external_id": external_id}, headers=api
    )
    subject.raise_for_status()
    subject_id = subject.json()["id"]

    enrolled = await client.post(
        f"{base}/v1/enrollments",
        json={"subject_id": subject_id, "images": [frame(identity, i + 1) for i in range(3)]},
        headers=api,
    )
    if enrolled.status_code != 201:
        raise SystemExit(f"could not enroll: {enrolled.status_code} {enrolled.text}")
    return secret, subject_id, identity


async def worker(
    client: httpx.AsyncClient,
    base: str,
    api_key: str,
    subject_id: str,
    identity: int,
    queue: asyncio.Queue[int],
    results: Results,
) -> None:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    while True:
        try:
            index = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        body = {"subject_id": subject_id, "image": frame(identity, 1000 + index)}
        started = time.perf_counter()
        try:
            response = await client.post(
                f"{base}/v1/verifications", json=body, headers=headers, timeout=30.0
            )
            elapsed = (time.perf_counter() - started) * 1000
            payload = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else None
            )
            results.record(response.status_code, elapsed, payload)
        except Exception as exc:
            results.errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            queue.task_done()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--email", default="owner@acme.example.com")
    parser.add_argument("--password", default="Password123!demo")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    async with httpx.AsyncClient() as client:
        health = await client.get(f"{args.base}/health")
        engine = health.json().get("face_engine", "unknown")

        api_key, subject_id, identity = await setup(client, args.base, args.email, args.password)

        queue: asyncio.Queue[int] = asyncio.Queue()
        for index in range(args.requests):
            queue.put_nowait(index)

        results = Results()
        started = time.perf_counter()
        await asyncio.gather(
            *[
                worker(client, args.base, api_key, subject_id, identity, queue, results)
                for _ in range(args.concurrency)
            ]
        )
        wall = time.perf_counter() - started

    latencies = results.latencies_ms
    report = {
        "engine": engine,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "wall_seconds": round(wall, 2),
        "throughput_rps": round(len(latencies) / wall, 1) if wall else 0,
        "statuses": results.statuses,
        "decisions": results.decisions,
        "errors": results.errors[:5],
        "latency_ms": {
            "min": round(min(latencies), 1) if latencies else None,
            "p50": round(percentile(latencies, 0.50), 1),
            "p95": round(percentile(latencies, 0.95), 1),
            "p99": round(percentile(latencies, 0.99), 1),
            "max": round(max(latencies), 1) if latencies else None,
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
        },
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"\n  engine under test : {engine}")
    print(f"  requests          : {args.requests} at concurrency {args.concurrency}")
    print(f"  wall time         : {report['wall_seconds']}s")
    print(f"  throughput        : {report['throughput_rps']} req/s")
    print(f"  statuses          : {results.statuses}")
    print(f"  decisions         : {results.decisions}")
    if results.errors:
        print(f"  errors            : {len(results.errors)} — {results.errors[0]}")

    print("\n  latency (successful requests only)")
    for label in ("min", "p50", "p95", "p99", "max"):
        print(f"    {label:4} {report['latency_ms'][label]:>8} ms")

    budget = 800
    p95 = report["latency_ms"]["p95"]
    verdict = "within" if p95 < budget else "OVER"
    print(f"\n  p95 {p95} ms vs {budget} ms budget: {verdict}")

    if engine == "fake":
        print(
            "\n  NOTE: this ran against FakeFaceEngine. These numbers measure the\n"
            "  framework — routing, auth, quota, rate limiting, database round\n"
            "  trips — and NOT ONNX inference. Phase 0 measured the real pipeline\n"
            "  at p95 331 ms for detect+embed on 2 CPU threads; add roughly that\n"
            "  to the figures above for a realistic production estimate."
        )

    return 0 if not results.errors else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
