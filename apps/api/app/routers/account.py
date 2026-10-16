"""The signed-in person's own security: two-step verification."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..ratelimit import login_rate_limit
from ..security import decrypt_secret, encrypt_secret, verify_password
from ..services import totp
from ..services.account_security import check_second_factor

router = APIRouter(prefix="/account", tags=["Account"])


class TwoFactorStatus(BaseModel):
    enabled: bool
    recovery_codes_left: int
    required_by_agency: bool


class TwoFactorSetup(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class DisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=20)


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


def _status(user: User) -> TwoFactorStatus:
    return TwoFactorStatus(enabled=user.totp_enabled, recovery_codes_left=user.recovery_codes_left,
                           required_by_agency=bool(user.agency and user.agency.require_two_factor))


def _issue_recovery_codes(db: Session, user: User) -> list[str]:
    codes = totp.new_recovery_codes()
    user.recovery_codes = [totp.hash_recovery(code) for code in codes]
    db.commit()
    return codes


@router.get("/2fa", response_model=TwoFactorStatus)
def two_factor_status(user: User = Depends(get_current_user)):
    return _status(user)


@router.post("/2fa/setup", response_model=TwoFactorSetup)
def two_factor_setup(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """A new secret to scan. Nothing changes until a code from it is confirmed."""
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="Two-step verification is already on")
    secret = totp.new_secret()
    user.totp_secret = encrypt_secret(secret)
    user.totp_last_step = 0
    db.commit()
    uri = totp.otpauth_uri(secret, user.email, user.agency.name if user.agency else "OpenNexus")
    return TwoFactorSetup(secret=secret, otpauth_uri=uri, qr_svg=totp.qr_svg_data_uri(uri))


@router.post("/2fa/enable", response_model=RecoveryCodesOut, dependencies=[Depends(login_rate_limit)])
def two_factor_enable(payload: CodeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="Two-step verification is already on")
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Start the setup first")
    step = totp.verify(decrypt_secret(user.totp_secret), payload.code)
    if step is None:
        raise HTTPException(status_code=400, detail="That code is not valid. Check your phone's clock and try the newest code.")
    user.totp_enabled = True
    user.totp_last_step = step
    return RecoveryCodesOut(recovery_codes=_issue_recovery_codes(db, user))


@router.post("/2fa/recovery-codes", response_model=RecoveryCodesOut, dependencies=[Depends(login_rate_limit)])
def regenerate_recovery_codes(payload: CodeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """New recovery codes; the old ones stop working."""
    if not check_second_factor(db, user, payload.code):
        raise HTTPException(status_code=400, detail="That code is not valid")
    return RecoveryCodesOut(recovery_codes=_issue_recovery_codes(db, user))


@router.post("/2fa/disable", response_model=TwoFactorStatus, dependencies=[Depends(login_rate_limit)])
def two_factor_disable(payload: DisableIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not user.totp_enabled:
        return _status(user)
    if user.agency and user.agency.require_two_factor:
        raise HTTPException(status_code=409, detail="Your agency requires two-step verification")
    if not verify_password(payload.password, user.password_hash) or not check_second_factor(db, user, payload.code):
        raise HTTPException(status_code=400, detail="The password or the code is not valid")
    user.totp_enabled = False
    user.totp_secret = None
    user.recovery_codes = []
    db.commit()
    return _status(user)
