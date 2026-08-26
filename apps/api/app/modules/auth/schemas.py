"""Auth request and response contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    organization_name: str | None = Field(default=None, max_length=120)
    # Set when arriving from an invite link. The email is then locked to the
    # invitation so an invite cannot be redirected to another address.
    invitation_token: str | None = None

    @field_validator("email")
    @classmethod
    def _normalize(cls, value: str) -> str:
        # Normalising here means every downstream comparison is a plain equality
        # check, and the unique index actually enforces one account per address.
        return value.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    organization_id: str | None = None

    @field_validator("email")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str


class SwitchOrganizationRequest(BaseModel):
    """Re-issue the session against a different organization.

    Takes the refresh token rather than a password: the user has already
    authenticated, and forcing a re-login to change tenant would make multi-org
    membership unusable. Membership in the target org is verified server-side.
    """

    refresh_token: str
    organization_id: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    # Revokes every session for the user, not just this one.
    all_sessions: bool = False


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=12, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


# ── Responses ─────────────────────────────────────────────────────────────────


class OrganizationSummary(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    role: str


class UserProfile(BaseModel):
    id: str
    email: str
    full_name: str | None
    avatar_url: str | None
    email_verified: bool
    created_at: datetime


class SessionResponse(BaseModel):
    """What a successful login or refresh returns.

    The refresh token is returned in the body so the Next.js BFF can move it
    into an httpOnly cookie. It is never exposed to browser JavaScript — see
    docs/05-architecture.md §6.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserProfile
    organization: OrganizationSummary | None = None


class MeResponse(BaseModel):
    user: UserProfile
    organizations: list[OrganizationSummary]
    active_organization_id: str | None
    permissions: list[str]


class MessageResponse(BaseModel):
    """Deliberately vague for flows that must not disclose account existence."""

    message: str
