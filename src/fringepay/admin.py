"""Administrative commands for tenant and API credential lifecycle."""

from __future__ import annotations

import argparse
import asyncio

from fringepay.config import get_settings
from fringepay.persistence import Database, PaymentRepository


async def create_tenant(name: str) -> None:
    database = Database(get_settings().database_url)
    try:
        repository = PaymentRepository(database)
        tenant_id, api_key = await repository.create_tenant(name)
        print(f"Tenant ID: {tenant_id}")
        print(f"API key (shown once): {api_key}")
        print("Store this key in a secret manager; it cannot be retrieved later.")
    finally:
        await database.close()


async def revoke_api_key(tenant_id: str, key_prefix: str) -> None:
    database = Database(get_settings().database_url)
    try:
        repository = PaymentRepository(database)
        revoked = await repository.revoke_api_key(tenant_id, key_prefix)
        if not revoked:
            raise SystemExit("No active credential matched that tenant and prefix.")
        print("API credential revoked.")
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="fringepay-admin")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-tenant")
    create.add_argument("--name", required=True)

    revoke = commands.add_parser("revoke-api-key")
    revoke.add_argument("--tenant-id", required=True)
    revoke.add_argument("--key-prefix", required=True)

    args = parser.parse_args()
    if args.command == "create-tenant":
        asyncio.run(create_tenant(args.name))
    elif args.command == "revoke-api-key":
        asyncio.run(revoke_api_key(args.tenant_id, args.key_prefix))


if __name__ == "__main__":
    main()
