"""Organization, membership, and invitation contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.permissions import Role


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    logo_url: str | None = None
    billing_email: EmailStr | None = None


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    region: str
    logo_url: str | None
    billing_email: str | None
    member_count: int
    created_at: datetime


class OrgSettingsResponse(BaseModel):
    match_threshold: Decimal
    threshold_preset: str
    duplicate_check_enabled: bool
    duplicate_threshold: Decimal
    min_face_size_px: int
    require_liveness: bool
    max_templates_per_profile: int
    store_raw_images: bool
    image_retention_days: int
    log_retention_days: int


class OrgSettingsUpdate(BaseModel):
    # Only presets are offered here; a raw threshold is Owner-only and gated by
    # a separate permission, because loosening it weakens the whole tenant.
    threshold_preset: str | None = None
    match_threshold: Decimal | None = Field(default=None, gt=0, lt=1)
    duplicate_check_enabled: bool | None = None
    require_liveness: bool | None = None
    store_raw_images: bool | None = None
    image_retention_days: int | None = Field(default=None, ge=0, le=365)

    @field_validator("threshold_preset")
    @classmethod
    def _known_preset(cls, value: str | None) -> str | None:
        allowed = {"lenient", "balanced", "strict", "custom"}
        if value is not None and value not in allowed:
            raise ValueError(f"threshold_preset must be one of {sorted(allowed)}")
        return value


class MemberResponse(BaseModel):
    id: str
    user_id: str
    email: str
    full_name: str | None
    role: str
    status: str
    joined_at: datetime | None
    is_you: bool


class MemberRoleUpdate(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role = Role.DEVELOPER

    @field_validator("email")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


class InvitationIssued(InvitationResponse):
    """Returned once, at creation.

    The raw token is included so the console can render a shareable link while
    email delivery is not yet wired. Once delivery ships this field goes away —
    a token that appears in an API response is a token in an access log.
    """

    token: str


class InvitationPreview(BaseModel):
    """Unauthenticated view of an invite, for the acceptance screen.

    Deliberately minimal: it reveals the inviting organization and the target
    email, and nothing else about the tenant.
    """

    organization_name: str
    email: str
    role: str
    expires_at: datetime


class AcceptInvitationRequest(BaseModel):
    token: str
