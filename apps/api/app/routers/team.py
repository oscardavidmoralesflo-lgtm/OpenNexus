"""The agency's team: members, roles and invitations."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Invitation, User, now_utc
from ..ratelimit import login_rate_limit
from ..schemas import UserOut
from ..security import hash_password
from ..services.team_roles import MANAGERS, ROLES
from ..services.workspace_domain import describe

router = APIRouter(prefix="/team", tags=["Team"])
public_router = APIRouter(prefix="/auth/invitations", tags=["Team"])

INVITATION_DAYS = 7
ROLE_PATTERN = r"^(owner|admin|operator|viewer)$"


class MemberOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    two_factor_enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    is_you: bool


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    invited_by: str | None
    expires_at: datetime
    created_at: datetime


class InvitationCreated(InvitationOut):
    # Shown once: the only copy of the secret is in this link.
    link: str


class TeamOut(BaseModel):
    members: list[MemberOut]
    invitations: list[InvitationOut]
    require_two_factor: bool
    your_role: str


class InviteIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern=ROLE_PATTERN)


class RoleIn(BaseModel):
    role: str = Field(pattern=ROLE_PATTERN)


class PolicyIn(BaseModel):
    require_two_factor: bool


class InvitationPreview(BaseModel):
    agency_name: str
    email: str
    role: str
    expires_at: datetime


class AcceptIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=8, max_length=128)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_manager(user: User) -> None:
    if user.role not in MANAGERS:
        raise HTTPException(status_code=403, detail="Only owners and admins manage the team")


def _may_grant(actor: User, role: str) -> bool:
    """Owners grant any role; admins only operator and viewer."""
    return actor.role == "owner" or (actor.role == "admin" and role not in MANAGERS)


def _member_out(member: User, me: User) -> MemberOut:
    return MemberOut(id=member.id, name=member.name, email=member.email, role=member.role,
                     two_factor_enabled=member.totp_enabled, last_login_at=member.last_login_at,
                     created_at=member.created_at, is_you=member.id == me.id)


def _invitation_out(invitation: Invitation) -> dict:
    return {"id": invitation.id, "email": invitation.email, "role": invitation.role,
            "invited_by": invitation.invited_by.name if invitation.invited_by else None,
            "expires_at": invitation.expires_at, "created_at": invitation.created_at}


def _pending(db: Session, agency_id) -> list[Invitation]:
    return list(db.scalars(select(Invitation).where(
        Invitation.agency_id == agency_id, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None),
        Invitation.expires_at > now_utc(),
    ).order_by(Invitation.created_at.desc())))


def _owners(db: Session, agency_id) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.agency_id == agency_id, User.role == "owner")) or 0


def _member(db: Session, user: User, member_id: uuid.UUID) -> User:
    member = db.scalar(select(User).where(User.id == member_id, User.agency_id == user.agency_id))
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.get("", response_model=TeamOut)
def get_team(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    members = db.scalars(select(User).where(User.agency_id == user.agency_id).order_by(User.created_at)).all()
    invitations = _pending(db, user.agency_id) if user.role in MANAGERS else []
    return TeamOut(members=[_member_out(m, user) for m in members], invitations=[_invitation_out(i) for i in invitations],
                   require_two_factor=user.agency.require_two_factor, your_role=user.role)


@router.post("/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED)
def invite(payload: InviteIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_manager(user)
    if not _may_grant(user, payload.role):
        raise HTTPException(status_code=403, detail="Only an owner can invite owners and admins")
    email = payload.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Someone with that email already has an account")
    for previous in _pending(db, user.agency_id):
        if previous.email == email:
            previous.revoked_at = now_utc()
    token = secrets.token_urlsafe(32)
    invitation = Invitation(agency_id=user.agency_id, email=email, role=payload.role, token_hash=_hash(token),
                            invited_by_id=user.id, expires_at=now_utc() + timedelta(days=INVITATION_DAYS))
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    link = f"{describe(user.agency).primary_url.rstrip('/')}/invite/{token}"
    return {**_invitation_out(invitation), "link": link}


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_manager(user)
    invitation = db.scalar(select(Invitation).where(Invitation.id == invitation_id, Invitation.agency_id == user.agency_id))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    invitation.revoked_at = now_utc()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/members/{member_id}", response_model=MemberOut)
def change_role(member_id: uuid.UUID, payload: RoleIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_manager(user)
    member = _member(db, user, member_id)
    if member.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    if not _may_grant(user, member.role) or not _may_grant(user, payload.role):
        raise HTTPException(status_code=403, detail="Only an owner can change owners and admins")
    if member.role == "owner" and payload.role != "owner" and _owners(db, user.agency_id) <= 1:
        raise HTTPException(status_code=400, detail="The agency needs at least one owner")
    member.role = payload.role
    db.commit()
    return _member_out(member, user)


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(member_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_manager(user)
    member = _member(db, user, member_id)
    if member.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself")
    if not _may_grant(user, member.role):
        raise HTTPException(status_code=403, detail="Only an owner can remove owners and admins")
    if member.role == "owner" and _owners(db, user.agency_id) <= 1:
        raise HTTPException(status_code=400, detail="The agency needs at least one owner")
    # Their sessions stop working with the account; their MCP tokens go with it.
    db.delete(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/policy", response_model=TeamOut)
def set_policy(payload: PolicyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner changes the team's security policy")
    if payload.require_two_factor and not user.totp_enabled:
        raise HTTPException(status_code=400, detail="Turn on two-step verification for yourself first")
    user.agency.require_two_factor = payload.require_two_factor
    db.commit()
    return get_team(db, user)


def _open_invitation(db: Session, token: str) -> Invitation:
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == _hash(token)))
    if (invitation is None or invitation.accepted_at or invitation.revoked_at
            or invitation.expires_at <= now_utc()):
        raise HTTPException(status_code=404, detail="This invitation is no longer valid. Ask for a new one.")
    return invitation


@public_router.get("/{token}", response_model=InvitationPreview, dependencies=[Depends(login_rate_limit)])
def preview_invitation(token: str, db: Session = Depends(get_db)):
    invitation = _open_invitation(db, token)
    return InvitationPreview(agency_name=invitation.agency.name, email=invitation.email, role=invitation.role,
                             expires_at=invitation.expires_at)


@public_router.post("/{token}/accept", response_model=UserOut, status_code=status.HTTP_201_CREATED,
                    dependencies=[Depends(login_rate_limit)])
def accept_invitation(token: str, payload: AcceptIn, response: Response, db: Session = Depends(get_db)):
    from .auth import _signed_in

    invitation = _open_invitation(db, token)
    if invitation.role not in ROLES:
        raise HTTPException(status_code=400, detail="This invitation is no longer valid")
    if db.scalar(select(User.id).where(User.email == invitation.email)):
        raise HTTPException(status_code=409, detail="Someone with that email already has an account")
    user = User(agency_id=invitation.agency_id, name=payload.name.strip(), email=invitation.email,
                password_hash=hash_password(payload.password), role=invitation.role)
    invitation.accepted_at = now_utc()
    db.add(user)
    db.commit()
    db.refresh(user)
    response.status_code = status.HTTP_201_CREATED
    return _signed_in(db, response, user)
