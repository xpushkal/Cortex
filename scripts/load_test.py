"""Load-test driver (M4). Target: sustain 600 QPS on /search at p95 < 200 ms over
a 2M-chunk index; report p50/p95/p99 and throughput (docs/ARCHITECTURE.md §8).

Wraps a k6/locust run. Not part of PR CI — runs nightly/manual. Stub entrypoint.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("load test lands in M4")


if __name__ == "__main__":
    main()
