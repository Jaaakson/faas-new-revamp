"""Application configuration.

Every setting is typed and validated at import time. A missing or malformed
value raises immediately, so a misconfigured deploy fails in the first second
instead of serving broken requests for an hour.

Settings are read from the environment (and a local .env in development).
See .env.example at the repository root for the documented variable list.
"""

from __future__ import annotations

import json
import secrets
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "staging", "production", "test"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Unknown variables are ignored on purpose: .env.example documents
        # settings for later phases that this build does not consume yet.
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    ENVIRONMENT: Environment = "development"
    DEBUG: bool = False
    APP_NAME: str = "Fvas"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/v1"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fvas"
    DATABASE_POOL_SIZE: int = Field(default=10, ge=1, le=100)
    DATABASE_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DATABASE_ECHO: bool = False

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Security ──────────────────────────────────────────────────────────────
    # Phase 3 consumes these; declared now so the contract is stable and a
    # production deploy cannot start with a placeholder secret.
    JWT_SECRET_KEY: str = Field(default_factory=lambda: secrets.token_hex(32))
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, ge=1, le=1440)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30, ge=1, le=365)

    # NoDecode is required: pydantic-settings JSON-decodes complex types read
    # from env/dotenv sources *before* any validator runs, so the documented
    # comma-separated form would raise a parse error rather than reaching
    # `_split_origins` below.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    COOKIE_SECURE: bool = False
    COOKIE_DOMAIN: str = "localhost"

    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(default=30, ge=5, le=1440)
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = Field(default=24, ge=1, le=168)
    INVITATION_EXPIRE_DAYS: int = Field(default=7, ge=1, le=90)

    # Argon2id. Memory cost is in KiB — 65536 is 64 MiB, which is what makes
    # GPU cracking expensive. Lowering it in tests is not worth the fidelity
    # loss; the suite hashes only a handful of passwords.
    ARGON2_TIME_COST: int = Field(default=3, ge=1, le=10)
    ARGON2_MEMORY_COST: int = Field(default=65536, ge=8192)
    ARGON2_PARALLELISM: int = Field(default=4, ge=1, le=16)

    MAX_LOGIN_ATTEMPTS: int = Field(default=5, ge=3, le=20)
    LOCKOUT_DURATION_MINUTES: int = Field(default=15, ge=1, le=1440)

    # ── Face engine ───────────────────────────────────────────────────────────
    # `fake` is deterministic and needs no optional dependencies; it is the
    # default so tests and CI stay fast. Production must use `insightface` —
    # `build_engine()` refuses to start otherwise, because a fake engine in
    # production would accept every face.
    FACE_ENGINE: Literal["fake", "insightface"] = "fake"
    FACE_MODEL_NAME: str = "buffalo_l"
    # 320, not 640: measured at ~2.5x cheaper for recall the size gate discards
    # anyway (docs/14-phase-0-spike.md §2).
    FACE_DET_SIZE: int = Field(default=320, ge=160, le=1024)
    FACE_DET_THRESHOLD: float = Field(default=0.5, gt=0.0, lt=1.0)
    # ONNX Runtime defaults this to 0 = "every visible core", which inside a
    # CPU-quota'd container oversubscribes and measured 5x slower. Never 0.
    ONNX_INTRA_OP_THREADS: int = Field(default=2, ge=1, le=32)

    # Quality gates (docs/08-ai-workflow.md §2). Estimates, not measurements —
    # the Phase 0 spike calibrated the matching threshold, not these.
    MIN_FACE_SIZE_PX: float = Field(default=112.0, gt=0)
    MIN_SHARPNESS: float = Field(default=0.35, ge=0.0, le=1.0)
    MIN_BRIGHTNESS: float = Field(default=0.25, ge=0.0, le=1.0)
    MAX_BRIGHTNESS: float = Field(default=0.85, ge=0.0, le=1.0)
    MAX_YAW_DEGREES: float = Field(default=25.0, gt=0)
    MAX_PITCH_DEGREES: float = Field(default=20.0, gt=0)
    MAX_ROLL_DEGREES: float = Field(default=20.0, gt=0)

    # Enrollment
    MAX_ENROLLMENT_IMAGES: int = Field(default=5, ge=1, le=10)
    MAX_IMAGE_SIZE_MB: int = Field(default=8, ge=1, le=64)
    DEFAULT_MATCH_THRESHOLD: float = Field(default=0.38, gt=0.0, lt=1.0)
    DEFAULT_DUPLICATE_THRESHOLD: float = Field(default=0.60, gt=0.0, lt=1.0)

    # ── Observability ─────────────────────────────────────────────────────────
    SENTRY_DSN: str = ""
    METRICS_ENABLED: bool = True

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept both a comma-separated string and a JSON array.

        With NoDecode set, this validator owns parsing entirely — nothing
        decodes the raw string before it gets here.
        """
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if stripped.startswith("["):
            return json.loads(stripped)
        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        # Credentials are sent to the console origin; "*" would be both invalid
        # per the CORS spec and a real vulnerability. Fail loudly, not silently.
        if "*" in value:
            raise ValueError("CORS_ORIGINS must be an explicit allowlist, never '*'")
        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://") and not value.startswith(
            "sqlite+aiosqlite://"
        ):
            raise ValueError(
                "DATABASE_URL must use an async driver "
                "(postgresql+asyncpg://, or sqlite+aiosqlite:// in tests)"
            )
        return value

    # ── Derived ───────────────────────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT == "test"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def docs_url(self) -> str | None:
        """Interactive docs are disabled in production."""
        return None if self.is_production else "/docs"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redoc_url(self) -> str | None:
        return None if self.is_production else "/redoc"

    def assert_production_safe(self) -> None:
        """Guard against the configuration mistakes that are catastrophic in production.

        Called from the app lifespan so the process refuses to start rather
        than running with development defaults in front of real users.
        """
        if not self.is_production:
            return

        problems: list[str] = []
        if self.DEBUG:
            problems.append("DEBUG must be false in production")
        if not self.COOKIE_SECURE:
            problems.append("COOKIE_SECURE must be true in production")
        if len(self.JWT_SECRET_KEY) < 32:
            problems.append("JWT_SECRET_KEY must be at least 32 characters")
        if any(origin.startswith("http://") for origin in self.CORS_ORIGINS):
            problems.append("CORS_ORIGINS must use https in production")

        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Tests clear the cache via `get_settings.cache_clear()`."""
    return Settings()


settings = get_settings()
