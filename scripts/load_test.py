"""Load-test driver for `/v1/search` and `/v1/ask` (M4; docs/ARCHITECTURE.md §8).

A standalone async driver (httpx) — no server-side hooks — that fans out N
concurrent workers at a target API for a fixed duration and reports p50/p95/p99
latency + throughput. Equivalent in role to a k6/locust script; dependency-light
so it runs anywhere `httpx` is installed.

**Done-when target:** sustain 600 QPS on `/search` at p95 < 200 ms over a
2M-chunk index. Reproduce against a real deployment:

    just seed                        # or load a 2M-chunk corpus
    uv run uvicorn cortex.api.main:app --port 8000
    uv run python scripts/load_test.py --url http://localhost:8000 \
        --tenant demo --endpoint search --concurrency 64 --duration 30

CI does not gate on this (no scale env); it is the measurement tool, run against
a deployment that can actually serve the target.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Results:
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0

    def metrics(self, duration: float) -> dict[str, float]:
        n = len(self.latencies_ms)
        if n == 0:
            return {"requests": 0.0, "errors": float(self.errors)}
        s = sorted(self.latencies_ms)

        def pct(p: float) -> float:
            return s[min(n - 1, int(p / 100 * n))]

        return {
            "requests": float(n),
            "errors": float(self.errors),
            "throughput_rps": n / duration,
            "p50_ms": pct(50),
            "p95_ms": pct(95),
            "p99_ms": pct(99),
            "max_ms": max(s),
            "mean_ms": statistics.mean(s),
        }

    def report(self, duration: float) -> str:
        m = self.metrics(duration)
        if not m.get("requests"):
            return f"no successful requests ({self.errors} errors)"
        return (
            f"requests: {int(m['requests'])}  errors: {int(m['errors'])}\n"
            f"throughput: {m['throughput_rps']:.1f} req/s\n"
            f"latency ms  p50={m['p50_ms']:.1f}  p95={m['p95_ms']:.1f}  "
            f"p99={m['p99_ms']:.1f}  max={m['max_ms']:.1f}  mean={m['mean_ms']:.1f}"
        )


def _payload(endpoint: str, query: str, k: int) -> dict[str, object]:
    if endpoint == "ask":
        return {"q": query, "max_context": k}
    return {"q": query, "k": k}


async def _worker(
    client: httpx.AsyncClient,
    *,
    path: str,
    headers: dict[str, str],
    payload: dict[str, object],
    deadline: float,
    results: Results,
) -> None:
    while time.monotonic() < deadline:
        start = time.monotonic()
        try:
            resp = await client.post(path, json=payload, headers=headers)
            elapsed = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                results.latencies_ms.append(elapsed)
            else:
                results.errors += 1
        except httpx.HTTPError:
            results.errors += 1


async def run(args: argparse.Namespace) -> Results:
    path = f"/v1/{args.endpoint}"
    headers = {"X-Tenant": args.tenant}
    payload = _payload(args.endpoint, args.query, args.k)
    results = Results()
    deadline = time.monotonic() + args.duration
    async with httpx.AsyncClient(base_url=args.url, timeout=10.0) as client:
        await asyncio.gather(
            *(
                _worker(
                    client,
                    path=path,
                    headers=headers,
                    payload=payload,
                    deadline=deadline,
                    results=results,
                )
                for _ in range(args.concurrency)
            )
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Cortex load test (/search, /ask).")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--endpoint", choices=["search", "ask"], default="search")
    parser.add_argument("--query", default="refund approval over 500")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--json", action="store_true", help="emit metrics as JSON")
    # Optional budgets — exit non-zero if unmet, so a deployment can gate on this.
    parser.add_argument("--max-p95-ms", type=float, help="fail if p95 latency exceeds this")
    parser.add_argument("--min-rps", type=float, help="fail if throughput is below this")
    args = parser.parse_args()

    start = time.monotonic()
    results = asyncio.run(run(args))
    elapsed = time.monotonic() - start
    metrics = results.metrics(elapsed)

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(f"# load test: {args.endpoint} x{args.concurrency} for {args.duration}s")
        print(results.report(elapsed))

    failures = []
    if args.max_p95_ms is not None and metrics.get("p95_ms", float("inf")) > args.max_p95_ms:
        failures.append(f"p95 {metrics.get('p95_ms', 0):.1f}ms > budget {args.max_p95_ms}ms")
    if args.min_rps is not None and metrics.get("throughput_rps", 0.0) < args.min_rps:
        failures.append(
            f"throughput {metrics.get('throughput_rps', 0):.1f} < budget {args.min_rps}"
        )
    if metrics.get("requests", 0.0) == 0.0:
        failures.append("no successful requests")
    if failures:
        print("BUDGET FAILED: " + "; ".join(failures), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
