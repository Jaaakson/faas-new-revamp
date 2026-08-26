"""Identity and tenancy models.

The distinction that matters most (docs/06-database.md §3): a `User` is someone
on the customer's team who logs into the console. A `Subject` (Phase 5) is one of
*their* end users whose face gets verified. Different scale, different auth,
different lifecycle, different deletion obligations — so they are different
tables and always will be.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import (
    Base,
    IDMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UTCDateTime,
)
from app.shared.utils import ids

# Enum-like columns are VARCHAR + CHECK rather than native Postgres ENUMs.
# Adding a value to a native enum requires ALTER TYPE, which cannot run inside a
# transaction on older Postgres and complicates every rollback. A CHECK
# constraint gives the same validation with a migration that is trivially
# reversible.
# JSONB on PostgreSQL, JSON elsewhere. Matches the variant used in the
# biometrics module so the two never disagree about storage.
JsonColumn = JSON().with_variant(JSONB(), "postgresql")

PLANS = ("free", "startup", "growth", "enterprise")
MEMBERSHIP_STATUSES = ("active", "suspended")
INVITATION_STATUSES = ("pending", "accepted", "revoked", "expired")
THRESHOLD_PRESETS = ("lenient", "balanced", "strict", "custom")


def _check(column: str, allowed: tuple[str, ...], name: str) -> CheckConstraint:
    values = ", ".join(f"'{value}'" for value in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=name)


class Organization(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """The tenant boundary. Every tenant-owned row points here."""

    __id_prefix__ = ids.ORGANIZATION

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(
        String(20), nullable=False, default="free", server_default="free"
    )
    # Data-residency marker. Enforced at deploy time; recorded here so an
    # auditor can see which region a tenant was provisioned in.
    region: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ap-southeast", server_default="ap-southeast"
    )
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    settings: Mapped[OrgSettings] = relationship(
        back_populates="organization",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    __table_args__ = (
        _check("plan", PLANS, "ck_organizations_plan"),
        Index("ix_organizations_slug", "slug"),
    )


class OrgSettings(Base, TimestampMixin):
    """Per-tenant configuration, split from `organizations`.

    Separate table because it changes on a different cadence and is read on the
    verification hot path, where loading the parent row's mutable columns would
    be wasted work.
    """

    # The base class pluralizer would produce "org_settingses"; an explicit
    # name overrides it. The convention is a default, not a straitjacket.
    __tablename__ = "org_settings"

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )

    # Matching — see docs/08-ai-workflow.md §3. These are measurements from a
    # calibration run, not preferences.
    match_threshold: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=Decimal("0.380"),
        server_default=text("0.380"),
    )
    threshold_preset: Mapped[str] = mapped_column(
        String(20), nullable=False, default="balanced", server_default="balanced"
    )
    duplicate_check_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Higher than match_threshold on purpose: a dedup false positive blocks a
    # legitimate user from onboarding at all.
    duplicate_threshold: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=Decimal("0.600"),
        server_default=text("0.600"),
    )

    # Quality gates
    min_face_size_px: Mapped[int] = mapped_column(
        Integer, nullable=False, default=112, server_default=text("112")
    )
    require_liveness: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    max_templates_per_profile: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default=text("5")
    )

    # Retention. store_raw_images defaults to False and must be enabled
    # deliberately — minimisation is the default, not an option.
    store_raw_images: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    image_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    log_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )

    ip_allowlist: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_signing_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="settings")

    __table_args__ = (
        _check("threshold_preset", THRESHOLD_PRESETS, "ck_org_settings_preset"),
        CheckConstraint(
            "match_threshold > 0 AND match_threshold < 1",
            name="ck_org_settings_match_threshold_range",
        ),
    )


class User(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """A console account. Global, not tenant-scoped — one user, many orgs."""

    __id_prefix__ = ids.USER

    # Stored lowercase and compared exactly. The blueprint specified CITEXT;
    # explicit normalisation was chosen instead because it is visible in the
    # code, testable on any database, and does not depend on a Postgres
    # extension for a correctness property. See docs/06-database.md §4.1.
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Progressive lockout state.
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_users_email", "email", unique=True),)

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None


class Permission(Base, IDMixin, TimestampMixin):
    """A `resource:action` capability. Seeded, never created at runtime."""

    __id_prefix__ = "perm"

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    resource: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Role(Base, IDMixin, TimestampMixin):
    """A named set of permissions.

    `organization_id` is nullable: NULL means a system role shared by every
    tenant. Tenant-defined custom roles slot in later without a migration.
    """

    __id_prefix__ = "role"

    organization_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_roles_org_slug"),)


class RolePermission(Base, TimestampMixin):
    """Join table. Seeded from the code matrix and asserted at startup."""

    role_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship(lazy="selectin")


class Membership(Base, IDMixin, TimestampMixin):
    """Links a user to an organization with a role.

    The many-to-many is what makes multi-org membership and org switching work
    without duplicating accounts.
    """

    __id_prefix__ = ids.MEMBERSHIP

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    joined_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
    role: Mapped[Role] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_memberships_org_user"),
        _check("status", MEMBERSHIP_STATUSES, "ck_memberships_status"),
        Index("ix_memberships_user", "user_id"),
        Index("ix_memberships_org", "organization_id", "status"),
    )


class Invitation(Base, IDMixin, TimestampMixin):
    """A pending invitation to join an organization.

    The token carries the org, role, and email. The email is locked at
    registration so an invite cannot be redirected to another address.
    """

    __id_prefix__ = "inv"

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    organization: Mapped[Organization] = relationship()
    role: Mapped[Role] = relationship(lazy="selectin")

    __table_args__ = (
        _check("status", INVITATION_STATUSES, "ck_invitations_status"),
        # One *live* invite per email per org. The predicate is what makes this
        # correct: a full unique index would permanently block re-inviting
        # someone whose earlier invite was revoked or expired. Both SQLite and
        # Postgres support partial indexes, so the same constraint holds in
        # tests and in production.
        Index(
            "uq_invitations_pending",
            "organization_id",
            "email",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_invitations_token", "token_hash"),
    )


API_KEY_ENVIRONMENTS = ("test", "live")


class ApiKey(Base, IDMixin, TimestampMixin):
    """A machine credential for the public `/v1` API.

    **The secret is never stored.** Only its SHA-256 digest, a short prefix for
    lookup, and the last four characters for display. A database dump therefore
    contains nothing that can authenticate.

    SHA-256 rather than Argon2, deliberately and unusually. The reasoning is
    entropy, not convenience: the secret is 32 URL-safe characters from
    `secrets.token_urlsafe` — around 190 bits — so there is no dictionary to
    attack and no benefit from a slow KDF. What a slow hash *would* buy is
    ~100 ms of latency on the hottest path in the product, per request
    (docs/05-architecture.md §6). A user-chosen password is the opposite case
    and uses Argon2id.

    No `deleted_at`. Revocation is a timestamp, not a soft delete: a revoked key
    must stay visible in the console so a customer can see what was revoked and
    when, and it must keep satisfying the foreign key on its audit entries.
    """

    __id_prefix__ = ids.API_KEY

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(8), nullable=False)

    # `fvas_live_9f2c` — the first few characters of the secret. Unique and
    # indexed, so authentication is one index hit rather than a scan that hashes
    # every key in the table.
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)

    # A subset of the organization's permissions, not a superset. Narrowing a
    # key below its creator's role is the point; widening it above would be a
    # privilege-escalation path.
    scopes: Mapped[list[str]] = mapped_column(
        JsonColumn, nullable=False, default=list, server_default=text("'[]'")
    )

    created_by_user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Coalesced through Redis and flushed at most once a minute. Writing this row
    # on every verification would put an UPDATE on the busiest path in the system
    # and create lock contention for a field nobody reads in real time
    # (docs/06-database.md §6).
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Set on the old key during a rotation. Both keys work until it passes,
    # which is what lets a customer redeploy without a window of 401s.
    rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Comma-separated CIDRs. Live keys only — a test key is expected to be used
    # from a laptop whose address changes.
    ip_allowlist: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("environment IN ('test', 'live')", name="ck_api_keys_environment"),
        Index("ix_api_keys_org_env", "organization_id", "environment"),
        Index("ix_api_keys_prefix", "key_prefix"),
    )
