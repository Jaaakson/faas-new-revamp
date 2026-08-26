"""Configuration validation and log redaction.

Both are guardrails that only matter when someone gets something wrong, which
is exactly why they need tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.logging import SENSITIVE_KEYS, _redact_sensitive

# ── Configuration ─────────────────────────────────────────────────────────────


def test_cors_origins_accepts_a_comma_separated_string() -> None:
    settings = Settings(CORS_ORIGINS="http://localhost:3000, https://app.fvas.io")
    assert settings.CORS_ORIGINS == ["http://localhost:3000", "https://app.fvas.io"]


def test_cors_origins_accepts_a_json_array() -> None:
    settings = Settings(CORS_ORIGINS='["https://app.fvas.io","https://fvas.io"]')
    assert settings.CORS_ORIGINS == ["https://app.fvas.io", "https://fvas.io"]


def test_cors_origins_loads_from_a_dotenv_file(tmp_path: Path) -> None:
    """Regression: the dotenv path is not the same code path as a kwarg.

    pydantic-settings JSON-decodes complex types read from env/dotenv sources
    before any validator runs, so the comma-separated form documented in
    .env.example raised a parse error while every kwarg-based test passed.
    Loading a real file is the only way to cover this.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ENVIRONMENT=development\n"
        "CORS_ORIGINS=http://localhost:3000,https://app.fvas.io\n"
        "DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/fvas\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

    assert settings.CORS_ORIGINS == ["http://localhost:3000", "https://app.fvas.io"]


def test_the_shipped_env_example_actually_loads() -> None:
    """.env.example is the file every new contributor copies to .env.

    If it does not parse, `docker compose up` fails on a clean clone — which is
    a stated Phase 1 definition-of-done item.

    Assertions are limited to fields the conftest does not export into the
    process environment: real env vars outrank a dotenv file by design, so
    asserting on DATABASE_URL here would test the harness, not the file.
    """
    example = Path(__file__).resolve().parents[3] / ".env.example"
    assert example.is_file(), f"expected .env.example at {example}"

    settings = Settings(_env_file=example)  # type: ignore[call-arg]

    assert settings.CORS_ORIGINS == ["http://localhost:3000"]
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 15
    assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 30
    assert settings.DATABASE_POOL_SIZE == 10
    assert settings.COOKIE_SECURE is False


def test_wildcard_cors_origin_is_rejected() -> None:
    """`*` with credentials is invalid per spec and a real vulnerability."""
    with pytest.raises(ValueError, match="never '\\*'"):
        Settings(CORS_ORIGINS="*")


def test_sync_database_driver_is_rejected() -> None:
    """A sync driver silently blocks the event loop under load."""
    with pytest.raises(ValueError, match="async driver"):
        Settings(DATABASE_URL="postgresql://user:pass@localhost/fvas")


def test_production_rejects_debug_mode() -> None:
    settings = Settings(
        ENVIRONMENT="production",
        DEBUG=True,
        COOKIE_SECURE=True,
        CORS_ORIGINS="https://app.fvas.io",
        JWT_SECRET_KEY="x" * 64,
    )
    with pytest.raises(RuntimeError, match="DEBUG must be false"):
        settings.assert_production_safe()


def test_production_rejects_plaintext_origins() -> None:
    settings = Settings(
        ENVIRONMENT="production",
        DEBUG=False,
        COOKIE_SECURE=True,
        CORS_ORIGINS="http://app.fvas.io",
        JWT_SECRET_KEY="x" * 64,
    )
    with pytest.raises(RuntimeError, match="https"):
        settings.assert_production_safe()


def test_production_rejects_a_short_secret() -> None:
    settings = Settings(
        ENVIRONMENT="production",
        DEBUG=False,
        COOKIE_SECURE=True,
        CORS_ORIGINS="https://app.fvas.io",
        JWT_SECRET_KEY="short",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        settings.assert_production_safe()


def test_valid_production_config_passes() -> None:
    settings = Settings(
        ENVIRONMENT="production",
        DEBUG=False,
        COOKIE_SECURE=True,
        CORS_ORIGINS="https://app.fvas.io",
        JWT_SECRET_KEY="x" * 64,
    )
    settings.assert_production_safe()  # must not raise
    assert settings.docs_url is None, "interactive docs must be off in production"


def test_development_config_is_not_held_to_production_rules() -> None:
    Settings(ENVIRONMENT="development", DEBUG=True).assert_production_safe()


# ── Log redaction ─────────────────────────────────────────────────────────────


def test_sensitive_top_level_keys_are_redacted() -> None:
    event = {"event": "login", "password": "hunter2", "email": "rani@acme.io"}

    redacted = _redact_sensitive(None, "info", event)

    assert redacted["password"] == "[redacted]"
    assert redacted["email"] == "rani@acme.io", "non-sensitive fields must survive"


def test_redaction_reaches_nested_structures() -> None:
    """Sensitive data usually arrives inside a payload, not at the top level."""
    event = {
        "event": "verification",
        "payload": {
            "subject_id": "sub_123",
            "image": "<base64 jpeg>",
            "nested": [{"embedding": [0.1, 0.2]}],
        },
    }

    redacted = _redact_sensitive(None, "info", event)

    assert redacted["payload"]["image"] == "[redacted]"
    assert redacted["payload"]["nested"][0]["embedding"] == "[redacted]"
    assert redacted["payload"]["subject_id"] == "sub_123"


def test_redaction_is_case_insensitive() -> None:
    redacted = _redact_sensitive(None, "info", {"Authorization": "Bearer abc"})
    assert redacted["Authorization"] == "[redacted]"


@pytest.mark.parametrize(
    "key", ["password", "access_token", "refresh_token", "api_key", "embedding", "image"]
)
def test_the_critical_fields_are_all_covered(key: str) -> None:
    """A biometric platform leaking any of these into logs is a breach."""
    assert key in SENSITIVE_KEYS
