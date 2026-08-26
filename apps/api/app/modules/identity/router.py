"""Organization, member, and invitation endpoints.

Every tenant-scoped route resolves its organization from the principal, never
from a path parameter. A caller cannot address another tenant even by guessing
an ID, because the ID is not part of the request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import Permission, Role
from app.dependencies.auth import CurrentPrincipal, Principal, require_permission
from app.dependencies.db import get_db
from app.modules.auth.schemas import MessageResponse
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    AcceptInvitationRequest,
    InvitationCreate,
    InvitationIssued,
    InvitationPreview,
    InvitationResponse,
    MemberResponse,
    MemberRoleUpdate,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
    OrgSettingsResponse,
    OrgSettingsUpdate,
)
from app.modules.identity.service import IdentityService

router = APIRouter(tags=["Organizations"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _to_response(service: IdentityService, organization_id: str) -> OrganizationResponse:
    organization = await service.get_organization(organization_id)
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        plan=organization.plan,
        region=organization.region,
        logo_url=organization.logo_url,
        billing_email=organization.billing_email,
        member_count=await service.member_count(organization.id),
        created_at=organization.created_at,
    )


# ── Organizations ─────────────────────────────────────────────────────────────


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
    description="The caller becomes its Owner. Any authenticated user may create one.",
)
async def create_organization(
    payload: OrganizationCreate, principal: CurrentPrincipal, session: DbSession
) -> OrganizationResponse:
    service = IdentityService(session)
    organization = await service.create_organization(user_id=principal.user_id, name=payload.name)
    return await _to_response(service, organization.id)


@router.get(
    "/organizations/current",
    response_model=OrganizationResponse,
    summary="The active organization",
)
async def current_organization(
    principal: Annotated[Principal, Depends(require_permission(Permission.ORGANIZATION_READ))],
    session: DbSession,
) -> OrganizationResponse:
    return await _to_response(IdentityService(session), principal.require_organization)


@router.patch(
    "/organizations/current",
    response_model=OrganizationResponse,
    summary="Update the active organization",
    responses={403: {"description": "Requires organization:update"}},
)
async def update_organization(
    payload: OrganizationUpdate,
    principal: Annotated[Principal, Depends(require_permission(Permission.ORGANIZATION_UPDATE))],
    session: DbSession,
) -> OrganizationResponse:
    service = IdentityService(session)
    await service.update_organization(
        organization_id=principal.require_organization,
        name=payload.name,
        logo_url=payload.logo_url,
        billing_email=payload.billing_email,
    )
    return await _to_response(service, principal.require_organization)


# ── Settings ──────────────────────────────────────────────────────────────────


@router.get(
    "/organizations/current/settings",
    response_model=OrgSettingsResponse,
    summary="Verification and retention settings",
)
async def get_settings(
    principal: Annotated[Principal, Depends(require_permission(Permission.SETTINGS_READ))],
    session: DbSession,
) -> OrgSettingsResponse:
    row = await IdentityService(session).get_settings(principal.require_organization)
    return OrgSettingsResponse.model_validate(row, from_attributes=True)


@router.patch(
    "/organizations/current/settings",
    response_model=OrgSettingsResponse,
    summary="Update settings",
    description=(
        "Changing the preset moves the match threshold with it. Setting a raw "
        "`match_threshold` additionally requires `threshold:update`, which only an "
        "Owner holds — loosening it weakens the posture for the whole tenant."
    ),
    responses={403: {"description": "Requires settings:update, or threshold:update"}},
)
async def update_settings(
    payload: OrgSettingsUpdate,
    principal: Annotated[Principal, Depends(require_permission(Permission.SETTINGS_UPDATE))],
    session: DbSession,
) -> OrgSettingsResponse:
    row = await IdentityService(session).update_settings(
        organization_id=principal.require_organization,
        can_set_threshold=principal.can(Permission.THRESHOLD_UPDATE),
        **payload.model_dump(exclude_unset=True),
    )
    return OrgSettingsResponse.model_validate(row, from_attributes=True)


# ── Members ───────────────────────────────────────────────────────────────────


@router.get(
    "/members",
    response_model=list[MemberResponse],
    summary="List members",
)
async def list_members(
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_READ))],
    session: DbSession,
) -> list[MemberResponse]:
    rows = await IdentityService(session).list_members(principal.require_organization)
    return [
        MemberResponse(
            id=membership.id,
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=membership.role.slug,
            status=membership.status,
            joined_at=membership.joined_at,
            is_you=user.id == principal.user_id,
        )
        for membership, user in rows
    ]


@router.patch(
    "/members/{membership_id}",
    response_model=MemberResponse,
    summary="Change a member's role",
    responses={
        403: {"description": "Admins cannot modify an Owner"},
        409: {"description": "Cannot demote the last Owner"},
    },
)
async def update_member_role(
    membership_id: str,
    payload: MemberRoleUpdate,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_UPDATE_ROLE))],
    session: DbSession,
) -> MemberResponse:
    service = IdentityService(session)
    membership, role_slug = await service.update_member_role(
        organization_id=principal.require_organization,
        membership_id=membership_id,
        new_role=payload.role,
        actor_role=principal.role or Role.VIEWER,
        actor_user_id=principal.user_id,
    )
    user = await session.get(User, membership.user_id)
    if user is None:  # pragma: no cover - the membership FK guarantees the row
        raise NotFoundError("Member not found.")
    return MemberResponse(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role_slug,
        status=membership.status,
        joined_at=membership.joined_at,
        is_you=user.id == principal.user_id,
    )


@router.delete(
    "/members/{membership_id}",
    response_model=MessageResponse,
    summary="Remove a member",
    responses={409: {"description": "Cannot remove the last Owner"}},
)
async def remove_member(
    membership_id: str,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_REMOVE))],
    session: DbSession,
) -> MessageResponse:
    await IdentityService(session).remove_member(
        organization_id=principal.require_organization,
        membership_id=membership_id,
        actor_role=principal.role or Role.VIEWER,
    )
    return MessageResponse(message="Member removed.")


# ── Invitations ───────────────────────────────────────────────────────────────


@router.post(
    "/invitations",
    response_model=InvitationIssued,
    status_code=status.HTTP_201_CREATED,
    summary="Invite someone to the organization",
    responses={409: {"description": "Already a member, or an invite is already pending"}},
)
async def create_invitation(
    payload: InvitationCreate,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_INVITE))],
    session: DbSession,
) -> InvitationIssued:
    invitation, token = await IdentityService(session).create_invitation(
        organization_id=principal.require_organization,
        email=payload.email,
        role=payload.role,
        invited_by=principal.user_id,
        actor_role=principal.role or Role.VIEWER,
    )
    return InvitationIssued(
        id=invitation.id,
        email=invitation.email,
        # payload.role, not invitation.role: the relationship is unloaded on a
        # freshly created row, and touching it would attempt implicit IO.
        role=payload.role.value,
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        token=token,
    )


@router.get(
    "/invitations",
    response_model=list[InvitationResponse],
    summary="List invitations",
)
async def list_invitations(
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_READ))],
    session: DbSession,
) -> list[InvitationResponse]:
    rows = await IdentityService(session).list_invitations(principal.require_organization)
    return [
        InvitationResponse(
            id=row.id,
            email=row.email,
            role=row.role.slug,
            status=row.status,
            expires_at=row.expires_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.delete(
    "/invitations/{invitation_id}",
    response_model=MessageResponse,
    summary="Revoke a pending invitation",
)
async def revoke_invitation(
    invitation_id: str,
    principal: Annotated[Principal, Depends(require_permission(Permission.MEMBER_INVITE))],
    session: DbSession,
) -> MessageResponse:
    await IdentityService(session).revoke_invitation(
        organization_id=principal.require_organization, invitation_id=invitation_id
    )
    return MessageResponse(message="Invitation revoked.")


@router.get(
    "/invitations/preview/{token}",
    response_model=InvitationPreview,
    summary="Preview an invitation before signing in",
    description=(
        "Unauthenticated: the recipient may not have an account yet. Returns only the "
        "inviting organization, the target address, and the role — nothing else about "
        "the tenant."
    ),
    responses={404: {"description": "Invitation not found or no longer valid"}},
)
async def preview_invitation(token: str, session: DbSession) -> InvitationPreview:
    invitation, organization = await IdentityService(session).preview_invitation(token)
    return InvitationPreview(
        organization_name=organization.name,
        email=invitation.email,
        role=invitation.role.slug,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/invitations/accept",
    response_model=MessageResponse,
    summary="Accept an invitation as the signed-in user",
    responses={403: {"description": "The invitation was issued to another address"}},
)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    principal: CurrentPrincipal,
    session: DbSession,
) -> MessageResponse:
    user = await session.get(User, principal.user_id)
    if user is None:  # pragma: no cover - principal resolution already loaded it
        raise NotFoundError("Account not found.")
    await IdentityService(session).accept_invitation(token=payload.token, user=user)
    return MessageResponse(message="You have joined the organization.")
