"""Plans, AI credit and payments, when the deployment turns billing on."""

import json
import logging
from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..services import billing
from ..services.workspace_domain import describe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])
public_router = APIRouter(prefix="/billing", tags=["Billing"])


class CheckoutIn(BaseModel):
    plan_id: str


class TopupIn(BaseModel):
    amount: int


class RedirectOut(BaseModel):
    url: str


class TransactionOut(BaseModel):
    id: uuid.UUID
    kind: str
    amount_usd: float
    balance_after: float
    description: str
    created_at: datetime


def _require_enabled() -> None:
    if not billing.enabled():
        raise HTTPException(status_code=404, detail="Billing is not enabled on this installation")


def _return_url(user: User) -> str:
    return f"{describe(user.agency).primary_url.rstrip('/')}/billing"


@router.get("")
def billing_overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return billing.overview(db, user.agency)


@router.get("/spend")
def billing_spend(days: int = 30, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    return billing.spend(db, user.agency_id, max(1, min(days, 366)))


@router.get("/transactions", response_model=list[TransactionOut])
def billing_transactions(limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    return [{"id": t.id, "kind": t.kind, "amount_usd": float(t.amount_usd), "balance_after": float(t.balance_after),
             "description": t.description, "created_at": t.created_at} for t in billing.transactions(db, user.agency_id, limit)]


@router.post("/checkout", response_model=RedirectOut)
async def billing_checkout(payload: CheckoutIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    plan = billing.plan_by_id(payload.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Unknown plan")
    return {"url": await billing.checkout_plan(db, user.agency, user.email, plan, _return_url(user))}


@router.post("/topup", response_model=RedirectOut)
async def billing_topup(payload: TopupIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    return {"url": await billing.checkout_topup(db, user.agency, user.email, payload.amount, _return_url(user))}


@router.post("/portal", response_model=RedirectOut)
async def billing_portal(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_enabled()
    return {"url": await billing.portal(db, user.agency, user.email, _return_url(user))}


@public_router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None), db: Session = Depends(get_db)):
    payload = await request.body()
    if not billing.verify_signature(payload, stripe_signature, get_settings().stripe_webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid signature")
    try:
        event = json.loads(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid payload") from exc
    outcome = billing.handle_event(db, event)
    logger.info("Stripe event %s (%s): %s", event.get("id"), event.get("type"), outcome)
    return {"received": True, "outcome": outcome}
