"""Organization, membership, and invitation logic.

Holds the invariant that matters most for tenancy: an organization always has at
least one active Owner. Expressing that as a database constraint would need a
trigger with a partial count, so it is centralized here and covered by tests —
which is why every path that could remove an Owner goes through this service.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.core.permissions import Role as RoleEnum
from app.core.security import generate_token, hash_token
from app.modules.identity.models import (
    Invitation,
    Membership,
    Organization,
    OrgSettings,
    User,
)
from app.modules.identity.seed import get_system_role

logger = structlog.get_logger(__name__)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "org"


class IdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Organizations ─────────────────────────────────────────────────────────

    async def create_organization(self, *, user_id: str, name: str) -> Organization:
        base = _slugify(name)
        slug = base
        suffix = 1
        while await self.session.scalar(select(Organization.id).where(Organization.slug == slug)):
            suffix += 1
            slug = f"{base}-{suffix}"

        organization = Organization(name=name, slug=slug)
        self.session.add(organization)
        await self.session.flush()

        self.session.add(OrgSettings(organization_id=organization.id))

        owner_role = await get_system_role(self.session, RoleEnum.OWNER)
        self.session.add(
            Membership(
                organization_id=organization.id,
                user_id=user_id,
                role_id=owner_role.id,
                status="active",
                joined_at=datetime.now(tz=UTC),
            )
        )
        await self.session.commit()
        logger.info("organization_created", organization_id=organization.id)
        return organization

    async def get_organization(self, organization_id: str) -> Organization:
        organization = await self.session.get(Organization, organization_id)
        if organization is None or organization.deleted_at is not None:
            raise NotFoundError("Organization not found.")
        return organization

    async def member_count(self, organization_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.status == "active",
                )
            )
            or 0
        )

    async def update_organization(self, *, organization_id: str, **values: object) -> Organization:
        organization = await self.get_organization(organization_id)
        for field, value in values.items():
            if value is not None:
                setattr(organization, field, value)
        await self.session.commit()
        return organization

    async def get_settings(self, organization_id: str) -> OrgSettings:
        settings_row = await self.session.get(OrgSettings, organization_id)
        if settings_row is None:
            # Every organization is created with settings; a missing row means
            # the data is inconsistent, not that the caller asked wrongly.
            raise NotFoundError("Organization settings not found.")
        return settings_row

    async def update_settings(
        self, *, organization_id: str, can_set_threshold: bool, **values: object
    ) -> OrgSettings:
        row = await self.get_settings(organization_id)

        preset_values = {
            "lenient": "0.320",
            "balanced": "0.380",
            "strict": "0.450",
        }

        explicit_threshold = values.get("match_threshold")
        if explicit_threshold is not None and not can_set_threshold:
            raise ForbiddenError(
                "Only an Owner can set a custom match threshold.",
                details={"required_permission": "threshold:update"},
            )

        for field, value in values.items():
            if value is None:
                continue
            setattr(row, field, value)

        # A preset must actually move the threshold, or the UI would show
        # "Strict" while the system keeps matching at the old value.
        preset = values.get("threshold_preset")
        if isinstance(preset, str) and preset in preset_values and explicit_threshold is None:
            from decimal import Decimal

            row.match_threshold = Decimal(preset_values[preset])
        if explicit_threshold is not None:
            row.threshold_preset = "custom"

        await self.session.commit()
        return row

    # ── Members ───────────────────────────────────────────────────────────────

    async def list_members(self, organization_id: str) -> list[tuple[Membership, User]]:
        rows = await self.session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at.asc())
        )
        return [(membership, user) for membership, user in rows]

    async def _get_membership(self, organization_id: str, membership_id: str) -> Membership:
        membership = await self.session.scalar(
            select(Membership).where(
                Membership.id == membership_id,
                Membership.organization_id == organization_id,
            )
        )
        if membership is None:
            # 404 rather than 403: a membership in another tenant must be
            # indistinguishable from one that does not exist.
            raise NotFoundError("Member not found.")
        return membership

    async def _active_owner_count(self, organization_id: str) -> int:
        owner_role = await get_system_role(self.session, RoleEnum.OWNER)
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.role_id == owner_role.id,
                    Membership.status == "active",
                )
            )
            or 0
        )

    async def _assert_not_last_owner(self, membership: Membership, action: str) -> None:
        """Refuse to leave an organization without an Owner.

        Without this an organization can be orphaned: nobody can manage billing,
        change the threshold, or invite a replacement — and no support path
        short of direct database access can fix it.
        """
        owner_role = await get_system_role(self.session, RoleEnum.OWNER)
        if membership.role_id != owner_role.id or membership.status != "active":
            return
        if await self._active_owner_count(membership.organization_id) <= 1:
            raise ConflictError(
                f"Cannot {action} the last Owner. Promote another member to Owner first.",
                code="last_owner",
            )

    async def update_member_role(
        self,
        *,
        organization_id: str,
        membership_id: str,
        new_role: RoleEnum,
        actor_role: RoleEnum,
        actor_user_id: str,
    ) -> tuple[Membership, str]:
        """Returns the membership and the *new* role slug.

        The slug is returned rather than read back from `membership.role`: with
        `expire_on_commit=False` that relationship still holds the previously
        loaded Role object after `role_id` changes, so the response would
        confidently report the old role.
        """
        membership = await self._get_membership(organization_id, membership_id)
        owner_role = await get_system_role(self.session, RoleEnum.OWNER)

        # An Admin manages the team but must not be able to demote the person
        # who can remove them.
        if actor_role is not RoleEnum.OWNER and membership.role_id == owner_role.id:
            raise ForbiddenError("Only an Owner can change another Owner's role.")
        if actor_role is not RoleEnum.OWNER and new_role is RoleEnum.OWNER:
            raise ForbiddenError("Only an Owner can promote someone to Owner.")

        if new_role is not RoleEnum.OWNER:
            await self._assert_not_last_owner(membership, "demote")

        # Self-demotion is allowed, but not into a state nobody can undo. The
        # last-owner check above already covers this; the separate message is
        # for the single-owner case, where "you" is clearer than "the last Owner".
        if (
            membership.user_id == actor_user_id
            and new_role is not RoleEnum.OWNER
            and await self._active_owner_count(organization_id) <= 1
        ):
            raise ConflictError(
                "You are the last Owner. Promote someone else before changing your role.",
                code="last_owner",
            )

        role = await get_system_role(self.session, new_role)
        membership.role_id = role.id
        await self.session.commit()
        logger.info(
            "member_role_changed",
            organization_id=organization_id,
            membership_id=membership_id,
            role=new_role.value,
        )
        return membership, new_role.value

    async def remove_member(
        self,
        *,
        organization_id: str,
        membership_id: str,
        actor_role: RoleEnum,
    ) -> None:
        membership = await self._get_membership(organization_id, membership_id)
        owner_role = await get_system_role(self.session, RoleEnum.OWNER)

        if actor_role is not RoleEnum.OWNER and membership.role_id == owner_role.id:
            raise ForbiddenError("Only an Owner can remove another Owner.")

        await self._assert_not_last_owner(membership, "remove")

        await self.session.delete(membership)
        await self.session.commit()
        logger.info("member_removed", organization_id=organization_id, membership_id=membership_id)

    # ── Invitations ───────────────────────────────────────────────────────────

    async def create_invitation(
        self,
        *,
        organization_id: str,
        email: str,
        role: RoleEnum,
        invited_by: str,
        actor_role: RoleEnum,
    ) -> tuple[Invitation, str]:
        if actor_role is not RoleEnum.OWNER and role is RoleEnum.OWNER:
            raise ForbiddenError("Only an Owner can invite another Owner.")

        already_member = await self.session.scalar(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id, User.email == email)
        )
        if already_member:
            raise ConflictError(
                "That person is already a member of this organization.",
                code="already_member",
            )

        pending = await self.session.scalar(
            select(Invitation).where(
                Invitation.organization_id == organization_id,
                Invitation.email == email,
                Invitation.status == "pending",
            )
        )
        if pending is not None:
            raise ConflictError(
                "An invitation is already pending for that address.",
                code="invitation_pending",
            )

        role_row = await get_system_role(self.session, role)
        raw_token = generate_token()
        invitation = Invitation(
            organization_id=organization_id,
            email=email,
            role_id=role_row.id,
            token_hash=hash_token(raw_token),
            invited_by_user_id=invited_by,
            expires_at=datetime.now(tz=UTC) + timedelta(days=settings.INVITATION_EXPIRE_DAYS),
        )
        self.session.add(invitation)
        await self.session.commit()
        logger.info("invitation_created", organization_id=organization_id)
        return invitation, raw_token

    async def list_invitations(self, organization_id: str) -> list[Invitation]:
        return list(
            await self.session.scalars(
                select(Invitation)
                .where(Invitation.organization_id == organization_id)
                .order_by(Invitation.created_at.desc())
            )
        )

    async def revoke_invitation(self, *, organization_id: str, invitation_id: str) -> None:
        invitation = await self.session.scalar(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.organization_id == organization_id,
            )
        )
        if invitation is None:
            raise NotFoundError("Invitation not found.")
        if invitation.status != "pending":
            raise BadRequestError("Only a pending invitation can be revoked.")

        invitation.status = "revoked"
        await self.session.commit()

    async def preview_invitation(self, token: str) -> tuple[Invitation, Organization]:
        """Unauthenticated lookup for the acceptance screen."""
        invitation = await self._load_pending_invitation(token)
        organization = await self.get_organization(invitation.organization_id)
        return invitation, organization

    async def accept_invitation(self, *, token: str, user: User) -> Membership:
        invitation = await self._load_pending_invitation(token)

        if invitation.email != user.email:
            raise ForbiddenError(
                "This invitation was issued to a different email address.",
                code="invitation_email_mismatch",
            )

        existing = await self.session.scalar(
            select(Membership).where(
                Membership.organization_id == invitation.organization_id,
                Membership.user_id == user.id,
            )
        )
        if existing is not None:
            invitation.status = "accepted"
            invitation.accepted_at = datetime.now(tz=UTC)
            await self.session.commit()
            return existing

        membership = Membership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            role_id=invitation.role_id,
            status="active",
            joined_at=datetime.now(tz=UTC),
        )
        self.session.add(membership)
        invitation.status = "accepted"
        invitation.accepted_at = datetime.now(tz=UTC)
        await self.session.commit()
        logger.info(
            "invitation_accepted",
            organization_id=invitation.organization_id,
            user_id=user.id,
        )
        return membership

    async def _load_pending_invitation(self, token: str) -> Invitation:
        invitation = await self.session.scalar(
            select(Invitation).where(Invitation.token_hash == hash_token(token))
        )
        if invitation is None or invitation.status != "pending":
            raise NotFoundError("This invitation is no longer valid.")
        if invitation.expires_at <= datetime.now(tz=UTC):
            invitation.status = "expired"
            await self.session.commit()
            raise BadRequestError("This invitation has expired.", code="invitation_expired")
        return invitation
