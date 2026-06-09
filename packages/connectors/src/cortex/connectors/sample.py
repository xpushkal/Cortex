"""Deterministic sample connector — seeds a synthetic corpus for tests + golden set.

Runnable: `python -m cortex.connectors.sample --tenant demo` (wired via `just seed`).
The seeding pipeline itself lands in M0; this is the CLI entrypoint stub.
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Cortex sample corpus.")
    parser.add_argument("--tenant", required=True, help="tenant id to seed into")
    args = parser.parse_args()
    raise NotImplementedError(
        f"sample seeding for tenant={args.tenant!r} lands in M0 "
        "(ingest sample corpus -> chunk -> embed -> Qdrant)"
    )


if __name__ == "__main__":
    main()
