"""Bearer-token auth: per-tenant API keys (docs/API.md).

A token is `ctx_<urlsafe-random>`; only its SHA-256 is persisted (`api_keys`).
Auth lookups run as the admin role on a dedicated session — `api_keys` is a
control-plane table outside row-level security, resolved before any tenant
context exists. Minting is a one-shot: the raw token is shown once.

CLI: `python -m cortex.api.auth mint --tenant demo --name laptop`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import secrets
import uuid

from sqlalchemy import func, select, update

from cortex.storage import ApiKey, get_sessionmaker, resolve_tenant

_TOKEN_PREFIX = "ctx_"


def generate_token() -> str:
    """Return a fresh opaque bearer token (shown to the user once)."""
    return f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    """SHA-256 hex of a token — what we store and look up by."""
    return hashlib.sha256(token.encode()).hexdigest()


async def mint_api_key(tenant_id: uuid.UUID, name: str, *, dsn: str | None = None) -> str:
    """Create an API key for a tenant and return the raw token (once)."""
    token = generate_token()
    async with get_sessionmaker(dsn)() as session:
        session.add(ApiKey(tenant_id=tenant_id, name=name, token_hash=hash_token(token)))
        await session.commit()
    return token


async def resolve_token_tenant(token: str, *, dsn: str | None = None) -> uuid.UUID | None:
    """Return the tenant a (non-revoked) token belongs to, or None.

    Records `last_used_at` on a hit. Runs as the admin role: `api_keys` is not
    tenant-scoped and must be readable before tenant context is set.
    """
    if not token.startswith(_TOKEN_PREFIX):
        return None
    digest = hash_token(token)
    async with get_sessionmaker(dsn)() as session:
        row = (
            await session.execute(
                select(ApiKey).where(ApiKey.token_hash == digest, ApiKey.revoked_at.is_(None))
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        await session.execute(
            update(ApiKey).where(ApiKey.id == row.id).values(last_used_at=func.now())
        )
        await session.commit()
        return row.tenant_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Cortex API keys.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    mint = sub.add_parser("mint", help="mint a new API key for a tenant")
    mint.add_argument("--tenant", required=True, help="tenant UUID or name")
    mint.add_argument("--name", default="default", help="human label for the key")
    args = parser.parse_args()

    if args.cmd == "mint":
        tenant = resolve_tenant(args.tenant)
        token = asyncio.run(mint_api_key(tenant, args.name))
        print(f"tenant={tenant} name={args.name}")
        print(f"token: {token}")
        print("Store it now — it is not recoverable.")


if __name__ == "__main__":
    main()
