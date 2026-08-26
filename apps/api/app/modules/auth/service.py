"""Authentication business logic.

Knows nothing about HTTP: it raises domain exceptions and returns values, which
is what lets the same code run from a CLI or a test without an ASGI stack. The
service method is the transaction boundary — it commits, routers never do.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthenticatedError,
)
from app.core.permissions import Role as RoleEnum
from app.core.permissions import permissions_for
from app.core.security import (
    PasswordPolicyError,
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    needs_rehash,
    validate_password,
    verify_password,
)
from app.modules.auth.models import (
    AuthEvent,
    AuthLog,
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
)
from app.modules.auth.schemas import (
    OrganizationSummary,
    SessionResponse,
    UserProfile,
)
from app.modules.identity.models import Invitation, Membership, Organization, OrgSettings, User
from app.modules.identity.seed import get_system_role
from app.shared.utils import ids

logger = structlog.get_logger(__name__)

# A deliberately vague message. Returned identically whether or not the address
# exists, so the endpoint cannot be used to enumerate accounts.
RESET_SENT_MESSAGE = "If an account exists for that address, a password reset link has been sent."


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "org"


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(
        self,
        event: str,
        *,
        user_id: str | None = None,
        email: str | None = None,
        success: bool = True,
        detail: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.session.add(
            AuthLog(
                user_id=user_id,
                email=email,
                event=event,
                success=success,
                detail=detail,
                ip_address=ip,
                user_agent=(user_agent or "")[:255] or None,
            )
        )

    # ── Registration ──────────────────────────────────────────────────────────

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        organization_name: str | None,
        invitation_token: str | None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, str]:
        """Create an account. Returns the user and the email verification token."""
        try:
            validate_password(password, email=email)
        except PasswordPolicyError as exc:
            raise BadRequestError(str(exc), code="weak_password") from exc

        existing = await self.session.scalar(select(User).where(User.email == email))
        if existing is not None:
            # Registration is one of the few places where disclosing existence
            # is unavoidable — the user must be told to sign in instead. The
            # mitigation is rate limiting, not vagueness.
            raise ConflictError("An account with this email already exists.", code="email_taken")

        invitation: Invitation | None = None
        if invitation_token:
            invitation = await self._load_valid_invitation(invitation_token)
            if invitation.email != email:
                raise BadRequestError(
                    "This invitation was issued to a different email address.",
                    code="invitation_email_mismatch",
                )

        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name.strip(),
        )
        self.session.add(user)
        await self.session.flush()

        if invitation is not None:
            # Joining an existing org: the inviter already chose the role, and
            # no personal organization is created.
            self.session.add(
                Membership(
                    organization_id=invitation.organization_id,
                    user_id=user.id,
                    role_id=invitation.role_id,
                    status="active",
                    joined_at=datetime.now(tz=UTC),
                )
            )
            invitation.status = "accepted"
            invitation.accepted_at = datetime.now(tz=UTC)
            self._log(AuthEvent.INVITATION_ACCEPTED, user_id=user.id, email=email, ip=ip)
        else:
            await self._create_organization(
                user=user, name=organization_name or f"{full_name.strip()}'s workspace"
            )

        raw_token = generate_token()
        self.session.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(tz=UTC)
                + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
            )
        )

        self._log(AuthEvent.REGISTERED, user_id=user.id, email=email, ip=ip, user_agent=user_agent)
        await self.session.commit()

        logger.info("user_registered", user_id=user.id)
        return user, raw_token

    async def _create_organization(self, *, user: User, name: str) -> Organization:
        """Create an organization with the user as its Owner."""
        base_slug = _slugify(name)
        slug = base_slug
        suffix = 1
        while await self.session.scalar(select(Organization.id).where(Organization.slug == slug)):
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        organization = Organization(name=name[:120], slug=slug)
        self.session.add(organization)
        await self.session.flush()

        # Every organization gets settings immediately, so the verification hot
        # path never has to handle a missing row.
        self.session.add(OrgSettings(organization_id=organization.id))

        owner_role = await get_system_role(self.session, RoleEnum.OWNER)
        self.session.add(
            Membership(
                organization_id=organization.id,
                user_id=user.id,
                role_id=owner_role.id,
                status="active",
                joined_at=datetime.now(tz=UTC),
            )
        )
        await self.session.flush()
        return organization

    async def _load_valid_invitation(self, token: str) -> Invitation:
        invitation = await self.session.scalar(
            select(Invitation).where(Invitation.token_hash == hash_token(token))
        )
        if invitation is None or invitation.status != "pending":
            raise BadRequestError("This invitation is no longer valid.", code="invitation_invalid")
        if invitation.expires_at <= datetime.now(tz=UTC):
            invitation.status = "expired"
            raise BadRequestError("This invitation has expired.", code="invitation_expired")
        return invitation

    # ── Login ─────────────────────────────────────────────────────────────────

    async def login(
        self,
        *,
        email: str,
        password: str,
        organization_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> SessionResponse:
        user = await self.session.scalar(select(User).where(User.email == email))

        if user is None:
            # Hash anyway so a missing account and a wrong password take
            # comparable time. Without this the endpoint is an account oracle
            # measurable with a stopwatch.
            hash_password(password)
            self._log(
                AuthEvent.LOGIN_FAILED,
                email=email,
                success=False,
                detail="unknown_account",
                ip=ip,
                user_agent=user_agent,
            )
            await self.session.commit()
            raise UnauthenticatedError("Incorrect email or password.")

        now = datetime.now(tz=UTC)
        if user.locked_until and user.locked_until > now:
            self._log(
                AuthEvent.LOGIN_LOCKED,
                user_id=user.id,
                email=email,
                success=False,
                ip=ip,
                user_agent=user_agent,
            )
            await self.session.commit()
            raise ForbiddenError(
                "This account is temporarily locked after too many failed attempts.",
                code="account_locked",
                details={"locked_until": user.locked_until.isoformat()},
            )

        if not user.is_active or user.deleted_at is not None:
            self._log(
                AuthEvent.LOGIN_FAILED,
                user_id=user.id,
                email=email,
                success=False,
                detail="inactive",
                ip=ip,
            )
            await self.session.commit()
            raise UnauthenticatedError("Incorrect email or password.")

        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            detail = "bad_password"
            if user.failed_login_count >= settings.MAX_LOGIN_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
                user.failed_login_count = 0
                detail = "locked_out"
            self._log(
                AuthEvent.LOGIN_FAILED,
                user_id=user.id,
                email=email,
                success=False,
                detail=detail,
                ip=ip,
                user_agent=user_agent,
            )
            await self.session.commit()
            raise UnauthenticatedError("Incorrect email or password.")

        # Success: clear lockout state and transparently upgrade the hash if the
        # Argon2 parameters have been raised since it was written.
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        membership = await self._resolve_membership(user.id, organization_id)

        self._log(
            AuthEvent.LOGIN_SUCCESS,
            user_id=user.id,
            email=email,
            ip=ip,
            user_agent=user_agent,
        )
        session_response = await self._issue_session(
            user=user, membership=membership, ip=ip, user_agent=user_agent
        )
        await self.session.commit()
        return session_response

    async def _resolve_membership(
        self, user_id: str, organization_id: str | None
    ) -> Membership | None:
        """Pick the active organization for a session."""
        query = select(Membership).where(
            Membership.user_id == user_id, Membership.status == "active"
        )
        if organization_id:
            query = query.where(Membership.organization_id == organization_id)
        # Deterministic default when none is requested: the earliest membership,
        # which for most users is their own workspace.
        query = query.order_by(Membership.created_at.asc())
        membership: Membership | None = await self.session.scalar(query)
        return membership

    # ── Sessions ──────────────────────────────────────────────────────────────

    async def _issue_session(
        self,
        *,
        user: User,
        membership: Membership | None,
        ip: str | None,
        user_agent: str | None,
        family_id: str | None = None,
    ) -> SessionResponse:
        role = membership.role.slug if membership else None
        access_token, expires_at = create_access_token(
            user_id=user.id,
            organization_id=membership.organization_id if membership else None,
            role=role,
        )

        raw_refresh = generate_token()
        refresh = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            # A new family per login; a rotation keeps the existing one, which
            # is what lets reuse detection revoke exactly one lineage.
            family_id=family_id or ids.new_id("fam"),
            expires_at=datetime.now(tz=UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            user_agent=(user_agent or "")[:255] or None,
            ip_address=ip,
        )
        self.session.add(refresh)
        await self.session.flush()

        organization = None
        if membership is not None:
            # session.get(), not membership.organization: attribute access on an
            # unloaded relationship attempts implicit IO, which an async session
            # cannot do outside the greenlet context.
            org = await self.session.get(Organization, membership.organization_id)
            if org is not None:
                organization = OrganizationSummary(
                    id=org.id, name=org.name, slug=org.slug, plan=org.plan, role=role or ""
                )

        return SessionResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_at=expires_at,
            user=_profile(user),
            organization=organization,
        )

    async def refresh(
        self,
        *,
        refresh_token: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> SessionResponse:
        """Rotate a refresh token, detecting reuse.

        Presenting an already-revoked token means it was stolen — either the
        attacker or the legitimate user is replaying it. Revoking the whole
        family turns an undetectable persistent compromise into a logged event
        and forces re-authentication.
        """
        token_row = await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
        )
        if token_row is None:
            raise UnauthenticatedError("The refresh token is invalid.")

        now = datetime.now(tz=UTC)

        if token_row.revoked_at is not None:
            await self._revoke_family(token_row.family_id, reason="reuse_detected")
            self._log(
                AuthEvent.TOKEN_REUSE_DETECTED,
                user_id=token_row.user_id,
                success=False,
                detail=f"family={token_row.family_id}",
                ip=ip,
                user_agent=user_agent,
            )
            await self.session.commit()
            logger.warning(
                "refresh_token_reuse_detected",
                user_id=token_row.user_id,
                family_id=token_row.family_id,
            )
            raise UnauthenticatedError(
                "This session has been revoked. Please sign in again.",
                code="token_reuse_detected",
            )

        if token_row.expires_at <= now:
            raise UnauthenticatedError("The refresh token has expired.")

        user = await self.session.get(User, token_row.user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            raise UnauthenticatedError("This account is no longer active.")

        membership = await self._resolve_membership(user.id, None)

        new_session = await self._issue_session(
            user=user,
            membership=membership,
            ip=ip,
            user_agent=user_agent,
            family_id=token_row.family_id,
        )

        # Revoke only after the replacement exists, so a crash mid-rotation
        # leaves the old token usable rather than locking the user out.
        replacement = await self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(new_session.refresh_token)
            )
        )
        token_row.revoked_at = now
        token_row.replaced_by_id = replacement.id if replacement else None

        self._log(AuthEvent.TOKEN_REFRESHED, user_id=user.id, ip=ip)
        await self.session.commit()
        return new_session

    async def switch_organization(
        self,
        *,
        refresh_token: str,
        organization_id: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> SessionResponse:
        """Issue a session scoped to a different organization.

        Rotates the refresh token exactly as `refresh` does, so switching does
        not create a second live lineage — that would defeat reuse detection by
        leaving an un-rotated token valid alongside the new one.
        """
        token_row = await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
        )
        now = datetime.now(tz=UTC)

        if token_row is None or token_row.revoked_at is not None:
            raise UnauthenticatedError("The refresh token is invalid.")
        if token_row.expires_at <= now:
            raise UnauthenticatedError("The refresh token has expired.")

        user = await self.session.get(User, token_row.user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            raise UnauthenticatedError("This account is no longer active.")

        membership = await self._resolve_membership(user.id, organization_id)
        if membership is None:
            # Not a member — or the org does not exist. Indistinguishable on
            # purpose: confirming existence would leak across the boundary.
            raise NotFoundError("Organization not found.")

        new_session = await self._issue_session(
            user=user,
            membership=membership,
            ip=ip,
            user_agent=user_agent,
            family_id=token_row.family_id,
        )

        replacement = await self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(new_session.refresh_token)
            )
        )
        token_row.revoked_at = now
        token_row.replaced_by_id = replacement.id if replacement else None

        await self.session.commit()
        return new_session

    async def _revoke_family(self, family_id: str, *, reason: str) -> None:
        rows = await self.session.scalars(
            select(RefreshToken).where(
                RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)
            )
        )
        now = datetime.now(tz=UTC)
        for row in rows:
            row.revoked_at = now
        logger.info("refresh_family_revoked", family_id=family_id, reason=reason)

    async def logout(
        self,
        *,
        user_id: str,
        refresh_token: str | None,
        all_sessions: bool = False,
        ip: str | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)

        if all_sessions:
            rows = await self.session.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
                )
            )
            for row in rows:
                row.revoked_at = now
        elif refresh_token:
            presented = await self.session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
            )
            if presented is not None and presented.revoked_at is None:
                # Revoke the family, not just this token: the point of logout is
                # that the whole lineage stops working.
                await self._revoke_family(presented.family_id, reason="logout")

        self._log(AuthEvent.LOGOUT, user_id=user_id, ip=ip)
        await self.session.commit()

    # ── Email verification ────────────────────────────────────────────────────

    async def verify_email(self, *, token: str, ip: str | None = None) -> User:
        row = await self.session.scalar(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == hash_token(token)
            )
        )
        now = datetime.now(tz=UTC)
        if row is None or row.used_at is not None or row.expires_at <= now:
            raise BadRequestError(
                "This verification link is invalid or has expired.",
                code="verification_invalid",
            )

        user = await self.session.get(User, row.user_id)
        if user is None:
            raise BadRequestError("This verification link is invalid.")

        row.used_at = now
        if user.email_verified_at is None:
            user.email_verified_at = now

        self._log(AuthEvent.EMAIL_VERIFIED, user_id=user.id, email=user.email, ip=ip)
        await self.session.commit()
        return user

    async def issue_verification_token(self, user: User) -> str:
        raw = generate_token()
        self.session.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(tz=UTC)
                + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
            )
        )
        await self.session.commit()
        return raw

    # ── Password reset ────────────────────────────────────────────────────────

    async def request_password_reset(self, *, email: str, ip: str | None = None) -> str | None:
        """Issue a reset token if the account exists.

        Returns None for an unknown address, and the caller returns the *same*
        response either way. Anything that varies — status code, message, or
        timing — turns this into an account-enumeration oracle.
        """
        user = await self.session.scalar(select(User).where(User.email == email))

        self._log(
            AuthEvent.PASSWORD_RESET_REQUESTED,
            user_id=user.id if user else None,
            email=email,
            success=user is not None,
            ip=ip,
        )

        if user is None or not user.is_active:
            await self.session.commit()
            return None

        raw = generate_token()
        self.session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(tz=UTC)
                + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
            )
        )
        await self.session.commit()
        return raw

    async def reset_password(self, *, token: str, new_password: str, ip: str | None = None) -> None:
        row = await self.session.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token))
        )
        now = datetime.now(tz=UTC)
        if row is None or row.used_at is not None or row.expires_at <= now:
            raise BadRequestError(
                "This reset link is invalid or has expired.", code="reset_invalid"
            )

        user = await self.session.get(User, row.user_id)
        if user is None:
            raise BadRequestError("This reset link is invalid.", code="reset_invalid")

        try:
            validate_password(new_password, email=user.email)
        except PasswordPolicyError as exc:
            raise BadRequestError(str(exc), code="weak_password") from exc

        user.password_hash = hash_password(new_password)
        # A reset is the remedy for a suspected compromise, so it must also end
        # any session the attacker already holds.
        user.failed_login_count = 0
        user.locked_until = None
        row.used_at = now

        active = await self.session.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
        for refresh in active:
            refresh.revoked_at = now

        self._log(AuthEvent.PASSWORD_RESET_COMPLETED, user_id=user.id, email=user.email, ip=ip)
        await self.session.commit()

    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise UnauthenticatedError("Your current password is incorrect.")
        try:
            validate_password(new_password, email=user.email)
        except PasswordPolicyError as exc:
            raise BadRequestError(str(exc), code="weak_password") from exc

        user.password_hash = hash_password(new_password)
        self._log(AuthEvent.PASSWORD_CHANGED, user_id=user.id, email=user.email)
        await self.session.commit()

    # ── Profile ───────────────────────────────────────────────────────────────

    async def describe_user(
        self, *, user_id: str, active_organization_id: str | None
    ) -> tuple[User, list[OrganizationSummary], list[str]]:
        user = await self.session.get(User, user_id)
        if user is None:
            raise UnauthenticatedError("This account no longer exists.")

        memberships = list(
            await self.session.scalars(
                select(Membership).where(
                    Membership.user_id == user_id, Membership.status == "active"
                )
            )
        )

        summaries: list[OrganizationSummary] = []
        permissions: list[str] = []
        for membership in memberships:
            org = await self.session.get(Organization, membership.organization_id)
            if org is None or org.deleted_at is not None:
                continue
            summaries.append(
                OrganizationSummary(
                    id=org.id,
                    name=org.name,
                    slug=org.slug,
                    plan=org.plan,
                    role=membership.role.slug,
                )
            )
            if org.id == active_organization_id:
                permissions = sorted(
                    permission.value for permission in permissions_for(membership.role.slug)
                )

        return user, summaries, permissions


def _profile(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        email_verified=user.is_email_verified,
        created_at=user.created_at,
    )
