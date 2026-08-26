"""Operational CLI.

    python -m app.cli export-openapi > openapi.json
    python -m app.cli check-config
    python -m app.cli seed          # Phase 4

Commands run the same services the API does, which is possible precisely
because services know nothing about HTTP (docs/05-architecture.md §4).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable


def export_openapi(**_: object) -> int:
    """Print the OpenAPI schema to stdout.

    CI regenerates TypeScript types from this and fails on drift, which is what
    makes "the backend schema is the source of truth" enforceable rather than
    aspirational.
    """
    from app.main import create_app

    print(json.dumps(create_app().openapi(), indent=2, sort_keys=True))
    return 0


def check_config(**_: object) -> int:
    """Validate configuration and report the resolved values.

    Secrets are never printed — only whether they are set.
    """
    from app.core.config import settings

    try:
        settings.assert_production_safe()
    except RuntimeError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1

    print(f"environment   {settings.ENVIRONMENT}")
    print(f"log level     {settings.LOG_LEVEL} ({settings.LOG_FORMAT})")
    print(f"database      {settings.DATABASE_URL.split('@')[-1]}")
    print(f"redis         {settings.REDIS_URL.split('@')[-1]}")
    print(f"cors origins  {', '.join(settings.CORS_ORIGINS)}")
    print(f"jwt secret    {'set' if len(settings.JWT_SECRET_KEY) >= 32 else 'TOO SHORT'}")
    print("OK")
    return 0


def check_health(**_: object) -> int:
    """Probe the configured dependencies from the command line."""
    from app.core.database import check_database
    from app.core.redis import check_redis

    async def run() -> int:
        database_ok, redis_ok = await asyncio.gather(check_database(), check_redis())
        print(f"database  {'ok' if database_ok else 'UNREACHABLE'}")
        print(f"redis     {'ok' if redis_ok else 'UNREACHABLE'}")
        return 0 if (database_ok and redis_ok) else 1

    return asyncio.run(run())


def seed(*, reset: bool = False, **_: object) -> int:
    """Seed the RBAC rows and a realistic demo tenant."""
    from app.core.database import SessionFactory, dispose_engine
    from app.modules.identity.seed import seed_roles_and_permissions
    from app.modules.platform.seed_demo import DEMO_PASSWORD, DEMO_USERS, seed_demo

    async def run() -> int:
        async with SessionFactory() as session:
            await seed_roles_and_permissions(session)
            await session.commit()
            result = await seed_demo(session, reset=reset)

        await dispose_engine()

        if result.get("skipped"):
            print("Demo tenant already exists. Re-run with --reset to regenerate.")
        else:
            print(f"users          {result['users']}")
            print(f"subjects       {result['subjects']}")
            print(f"verifications  {result['verifications']}")
            print(f"rollup days    {result['rollup_days']}")

        print("\nSign in with any of:")
        for email, name, role in DEMO_USERS:
            print(f"  {email:24} {role.value:10} {name}")
        print(f"\nPassword: {DEMO_PASSWORD}")
        return 0

    return asyncio.run(run())


def retention(*, dry_run: bool = False, **_: object) -> int:
    """Delete data past each organization's retention window.

    Intended as a nightly job. Idempotent — a second run in the same night
    deletes nothing, because the first already did.
    """
    from app.core.database import SessionFactory, dispose_engine
    from app.modules.platform.retention import enforce_retention

    async def run() -> int:
        async with SessionFactory() as session:
            if dry_run:
                # Run inside a transaction that is rolled back, so the counts
                # are real rather than estimated, and nothing is destroyed.
                report = await enforce_retention(session)
                await session.rollback()
            else:
                report = await enforce_retention(session)

        await dispose_engine()

        print(f"organizations scanned        {report.organizations}")
        print(f"verification sessions deleted {report.verification_sessions}")
        print(f"audit logs deleted            {report.audit_logs}")
        print(f"webhook deliveries deleted    {report.webhook_deliveries}")
        if dry_run:
            print("\n(dry run — rolled back, nothing was deleted)")
        return 0

    return asyncio.run(run())


# Every command accepts `**_`, so the dispatcher can pass all flags to all of
# them. mypy infers the dict value type from the first entry and then objects
# to the rest; the uniform `**_: object` signature is what makes it safe.
COMMANDS: dict[str, Callable[..., int]] = {
    "export-openapi": export_openapi,
    "check-config": check_config,
    "check-health": check_health,
    "seed": seed,
    "retention": retention,
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Fvas API operations")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument(
        "--reset",
        action="store_true",
        help="seed: regenerate the demo tenant's data instead of skipping it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="retention: report what would be deleted, then roll back",
    )
    arguments = parser.parse_args()
    return COMMANDS[arguments.command](reset=arguments.reset, dry_run=arguments.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
