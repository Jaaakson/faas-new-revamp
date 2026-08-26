"""Authentication state: tokens and the auth event log.

These are global (not tenant-scoped) because they concern `users`, who exist
above any single organization.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import Base, IDMixin, TimestampMixin, UTCDateTime


class RefreshToken(Base, IDMixin, TimestampMixin):
    """A rotating refresh token.

    `family_id` is what makes reuse detection possible. Every refresh issues a
    new token in the same family and revokes the previous one. Presenting an
    already-used token means it was stolen — by the attacker or replayed by the
    legitimate user — so the entire family is revoked. That converts an
    otherwise undetectable persistent compromise into a loud, logged event.
    """

    __id_prefix__ = "rt"

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the token. The plaintext exists only in the user's cookie —
    # a database leak must not yield usable sessions.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    family_id: Mapped[str] = mapped_column(String(40), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    __table_args__ = (
        Index("ix_refresh_tokens_hash", "token_hash"),
        Index("ix_refresh_tokens_family", "family_id"),
        Index("ix_refresh_tokens_user", "user_id"),
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class PasswordResetToken(Base, IDMixin, TimestampMixin):
    """Single-use, 30-minute password reset token."""

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (Index("ix_password_reset_tokens_hash", "token_hash"),)


class EmailVerificationToken(Base, IDMixin, TimestampMixin):
    """Single-use, 24-hour email verification token."""

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (Index("ix_email_verification_tokens_hash", "token_hash"),)


class AuthLog(Base, IDMixin, TimestampMixin):
    """Console authentication events.

    Separate from `audit_logs` (Phase 4) because these concern global users
    rather than a tenant's data, and because a failed login has no organization
    to attribute it to.
    """

    # Nullable: a failed login for an unknown address has no user to point at,
    # and those attempts are exactly what you want recorded.
    user_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_auth_logs_user", "user_id", "created_at"),
        Index("ix_auth_logs_event", "event", "created_at"),
        Index("ix_auth_logs_email", "email"),
    )


class AuthEvent:
    """Event names written to `auth_logs`. Constants, not free text."""

    REGISTERED = "user.registered"
    LOGIN_SUCCESS = "login.success"
    LOGIN_FAILED = "login.failed"
    LOGIN_LOCKED = "login.locked"
    LOGOUT = "logout"
    TOKEN_REFRESHED = "token.refreshed"
    TOKEN_REUSE_DETECTED = "token.reuse_detected"
    EMAIL_VERIFIED = "email.verified"
    PASSWORD_RESET_REQUESTED = "password.reset_requested"
    PASSWORD_RESET_COMPLETED = "password.reset_completed"
    PASSWORD_CHANGED = "password.changed"
    INVITATION_ACCEPTED = "invitation.accepted"
