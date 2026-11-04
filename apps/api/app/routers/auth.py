import hmac
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Agency, User
from ..ratelimit import client_ip, login_rate_limit
from ..schemas import LoginRequest, RegisterRequest, TwoFactorLogin, UserOut
from ..security import (
    PASSWORD_RESET_MINUTES, create_access_token, create_password_reset_token, create_two_factor_challenge,
    decode_password_reset_token, decode_two_factor_challenge, hash_password, reset_token_matches, verify_password,
)
from ..services.email import email_enabled, send_email
from ..services import audit
from ..slugs import unique_slug


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _set_session_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=create_access_token(str(user.id)),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_minutes * 60,
        path="/",
    )


def _registration_open(db: Session) -> bool:
    return db.scalar(select(Agency.id).limit(1)) is None


@router.get("/status", dependencies=[Depends(login_rate_limit)])
def auth_status(db: Session = Depends(get_db)):
    # Public: lets the login page decide between first-run setup (no agency
    # yet) and sign-in only (single-agency instance already configured).
    has_agency = db.scalar(select(Agency.id).limit(1)) is not None
    return {
        "needs_setup": not has_agency,
        "registration_open": not has_agency,
        "setup_token_required": not has_agency and bool(get_settings().setup_token),
        "password_reset": has_agency and email_enabled(),
    }


class PasswordForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    lang: str = "es"


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=2000)
    new_password: str = Field(min_length=8, max_length=128)


_RESET_MAIL = {
    "es": (
        "Restablece tu contraseña de Agentaria",
        "Hola {name},\n\nPediste restablecer la contraseña de tu cuenta de Agentaria. Abre este enlace para elegir una nueva "
        "(vence en {minutes} minutos y sirve una sola vez):\n\n{link}\n\nSi no fuiste tú, ignora este correo: tu contraseña no cambia.",
    ),
    "en": (
        "Reset your Agentaria password",
        "Hi {name},\n\nYou asked to reset the password of your Agentaria account. Open this link to choose a new one "
        "(it expires in {minutes} minutes and works once):\n\n{link}\n\nIf it was not you, ignore this e-mail: your password does not change.",
    ),
}


@router.post("/password/forgot", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(login_rate_limit)])
async def forgot_password(payload: PasswordForgotIn, request: Request, db: Session = Depends(get_db)):
    """E-mail a reset link. Answers the same whether or not the address has an
    account, so it cannot be used to find out who has one."""
    if not email_enabled():
        raise HTTPException(status_code=409, detail="Password reset by e-mail is not set up on this installation")
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is not None:
        token = create_password_reset_token(str(user.id), user.password_hash)
        link = f"{get_settings().frontend_url.rstrip('/')}/login?reset={token}"
        subject, body = _RESET_MAIL["en" if payload.lang == "en" else "es"]
        sent = await send_email(user.email, subject, body.format(name=user.name or user.email, minutes=PASSWORD_RESET_MINUTES, link=link))
        _record_sign_in(db, request, user, "auth.password_reset_requested", 204 if sent else 502)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(login_rate_limit)])
def reset_password(payload: PasswordResetIn, request: Request, db: Session = Depends(get_db)):
    decoded = decode_password_reset_token(payload.token)
    user = None
    if decoded:
        try:
            user = db.get(User, uuid.UUID(decoded[0]))
        except ValueError:
            user = None
    if user is None or not reset_token_matches(decoded[1], user.password_hash):
        raise HTTPException(status_code=400, detail="This link is not valid anymore. Ask for a new one.")
    user.password_hash = hash_password(payload.new_password)
    # Two-step verification stays on: the next sign-in still asks for the code.
    _record_sign_in(db, request, user, "auth.password_reset", 204)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(login_rate_limit)],
)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    # There is no owner row to lock on first run. Serialize setup attempts on
    # the table, then check again after any earlier attempt commits or rolls
    # back. Ordinary reads remain available and the lock ends with the transaction.
    db.execute(text("LOCK TABLE agencies IN EXCLUSIVE MODE"))
    if not _registration_open(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is closed on this instance",
        )
    expected = get_settings().setup_token
    if expected and not hmac.compare_digest((payload.setup_token or "").encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The setup token is not valid")
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    agency_name = payload.agency_name.strip()
    agency = Agency(name=agency_name, slug=unique_slug(db, Agency, "slug", agency_name))
    user = User(
        agency=agency,
        name=payload.name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_session_cookie(response, user)
    return user


@router.post("/login", response_model=None, dependencies=[Depends(login_rate_limit)])
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        if user is not None:
            # A wrong password for a real account is worth seeing in the log.
            _record_sign_in(db, request, user, "auth.sign_in_failed", 401)
            db.commit()
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if user.totp_enabled:
        # The password was right; the session waits for the second step.
        return {"two_factor_required": True, "challenge": create_two_factor_challenge(str(user.id))}
    return _signed_in(db, response, user, request)


def _record_sign_in(db: Session, request: Request | None, user: User, action: str, status_code: int) -> None:
    audit.record(
        db, agency_id=user.agency_id, user=user, action=action,
        method=request.method if request else "", path=request.url.path if request else "",
        status_code=status_code, ip=client_ip(request) if request else "",
        user_agent=request.headers.get("user-agent", "") if request else "",
    )


def _signed_in(db: Session, response: Response, user: User, request: Request | None = None) -> UserOut:
    from ..models import now_utc

    user.last_login_at = now_utc()
    _record_sign_in(db, request, user, "auth.sign_in", 200)
    db.commit()
    db.refresh(user)
    _set_session_cookie(response, user)
    return UserOut.model_validate(user)


@router.post("/login/2fa", response_model=UserOut, dependencies=[Depends(login_rate_limit)])
def login_second_step(payload: TwoFactorLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    from ..services.account_security import check_second_factor

    user_id = decode_two_factor_challenge(payload.challenge)
    user = db.get(User, uuid.UUID(user_id)) if user_id else None
    if user is None or not user.totp_enabled:
        raise HTTPException(status_code=401, detail="The sign-in expired. Enter your password again.")
    if not check_second_factor(db, user, payload.code):
        _record_sign_in(db, request, user, "auth.sign_in_failed", 401)
        db.commit()
        raise HTTPException(status_code=401, detail="That code is not valid")
    return _signed_in(db, response, user, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie("access_token", path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
