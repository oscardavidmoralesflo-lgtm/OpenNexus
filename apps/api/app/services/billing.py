"""Plans and AI credit, for a deployment that hosts the workspace for an agency.

Off unless ``billing_enabled``. It plugs into the two seams the core offers
deployments, so the AI path is untouched:

* ``register_credential_fallback``: when the agency holds no key of its own,
  the platform's key answers while the agency has credit left;
* ``register_usage_hook``: every reply that key paid for is charged to the
  credit, at the reported cost (or the catalog's list price) times the markup.

Payments go through Stripe's REST API (Checkout for plans and top-ups, the
customer portal for invoices and cancelation, a signed webhook for the
outcome). Every credit movement is a ``CreditTransaction``; a payment or a
usage record is applied once however often it is reported.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Agency, Client, CreditTransaction, ProviderCredential, UsageRecord
from . import providers, usage
from .model_catalog import get_model

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("active", "trialing")
PLATFORM_PROVIDER = "openrouter"
SIX = Decimal("0.000001")


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_usd: float
    max_clients: int | None
    stripe_price_id: str = ""


DEFAULT_PLANS = [
    Plan("launch", "Launch", 49, 5),
    Plan("growth", "Growth", 149, 20),
    Plan("unlimited", "Unlimited", 349, None),
]


def enabled() -> bool:
    return get_settings().billing_enabled


def plans() -> list[Plan]:
    raw = get_settings().billing_plans.strip()
    if not raw:
        return DEFAULT_PLANS
    try:
        return [Plan(
            id=str(item["id"]), name=str(item.get("name") or item["id"]), price_usd=float(item.get("price_usd") or 0),
            max_clients=None if item.get("max_clients") is None else int(item["max_clients"]),
            stripe_price_id=str(item.get("stripe_price_id") or ""),
        ) for item in json.loads(raw)]
    except (ValueError, KeyError, TypeError):
        logger.error("BILLING_PLANS is not valid JSON plans; using the defaults")
        return DEFAULT_PLANS


def plan_by_id(plan_id: str) -> Plan | None:
    return next((plan for plan in plans() if plan.id == plan_id), None)


def current_plan(agency: Agency) -> Plan | None:
    """The plan in force: the subscribed one while it is paid, else the default."""
    if agency.subscription_status in ACTIVE_STATUSES and agency.plan:
        plan = plan_by_id(agency.plan)
        if plan:
            return plan
    return plan_by_id(get_settings().billing_default_plan)


def topup_amounts() -> list[int]:
    amounts = []
    for part in get_settings().billing_topup_amounts.split(","):
        try:
            value = int(float(part))
        except ValueError:
            continue
        if value > 0:
            amounts.append(value)
    return amounts or [10, 25, 50, 100]


# --- plan limits ------------------------------------------------------------

def clients_used(db: Session, agency_id) -> int:
    """Clients that count toward the plan: the sandbox never does."""
    return db.scalar(select(func.count()).select_from(Client).where(Client.agency_id == agency_id, Client.is_sandbox.is_(False))) or 0


def check_client_limit(db: Session, agency: Agency) -> None:
    if not enabled():
        return
    plan = current_plan(agency)
    if plan is None:
        raise HTTPException(status_code=402, detail="Choose a plan in Billing to add clients")
    if plan.max_clients is not None and clients_used(db, agency.id) >= plan.max_clients:
        raise HTTPException(status_code=402, detail=f"Your {plan.name} plan allows {plan.max_clients} clients. Upgrade it in Billing to add more.")


# --- credit -----------------------------------------------------------------

def _decimal(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(SIX, rounding=ROUND_HALF_UP)


def apply_credit(db: Session, agency_id, kind: str, amount, description: str = "", *,
                 reference: str | None = None, usage_record: UsageRecord | None = None) -> CreditTransaction | None:
    """Move the agency's credit by ``amount`` (signed) and write it down.

    Returns None when ``reference`` was already applied for this ``kind``. The
    agency row is locked for the update; the caller owns the commit.
    """
    if reference and db.scalar(select(CreditTransaction.id).where(CreditTransaction.kind == kind, CreditTransaction.reference == reference)):
        return None
    agency = db.scalar(select(Agency).where(Agency.id == agency_id).with_for_update())
    if agency is None:
        return None
    balance = _decimal(agency.credit_balance) + _decimal(amount)
    agency.credit_balance = balance
    transaction = CreditTransaction(
        agency_id=agency_id, kind=kind, amount_usd=_decimal(amount), balance_after=balance,
        description=description[:240], reference=reference,
    )
    if usage_record is not None:
        # Through the relationship, so the record is inserted before this row.
        transaction.usage_record = usage_record
    db.add(transaction)
    return transaction


def balance(agency: Agency) -> Decimal:
    return _decimal(agency.credit_balance)


def _owns_key(db: Session, agency_id, provider: str) -> bool:
    credential = db.scalar(select(ProviderCredential).where(ProviderCredential.agency_id == agency_id, ProviderCredential.provider == provider))
    return credential is not None and credential.enabled


def list_price(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    info = get_model(model)
    if info is None:
        return Decimal(0)
    return (Decimal(input_tokens) / 1000 * Decimal(str(info.input_price_per_1k))
            + Decimal(output_tokens) / 1000 * Decimal(str(info.output_price_per_1k)))


def lend(db: Session, agency_id, provider: str):
    """The credential fallback: the platform's key, while there is credit."""
    if not _can_lend(db, agency_id, provider):
        return None
    return providers.base_url_for(provider), get_settings().billing_platform_key


def _can_lend(db: Session, agency_id, provider: str) -> bool:
    settings = get_settings()
    if not settings.billing_enabled or not settings.billing_platform_key or provider != PLATFORM_PROVIDER:
        return False
    current = db.scalar(select(Agency.credit_balance).where(Agency.id == agency_id))
    return _decimal(current) > 0


def meter(db: Session, record: UsageRecord, completion, **_context) -> None:
    """The usage hook: charge a reply the platform's key paid for to the credit."""
    settings = get_settings()
    if not settings.billing_enabled or not settings.billing_platform_key or record.provider != PLATFORM_PROVIDER:
        return
    if _owns_key(db, record.agency_id, record.provider):
        return
    cost = _decimal(record.cost_usd) if record.cost_usd is not None else list_price(record.model, record.input_tokens, record.output_tokens)
    charge = (Decimal(cost) * Decimal(str(settings.billing_credit_markup))).quantize(SIX, rounding=ROUND_HALF_UP)
    if charge <= 0:
        return
    apply_credit(db, record.agency_id, "usage", -charge, f"{record.model} · {record.input_tokens}+{record.output_tokens} tokens",
                 reference=str(record.id), usage_record=record)


def install() -> None:
    """Plug billing into the credential and usage seams."""
    providers.register_credential_fallback(lend, available=_can_lend)
    usage.register_usage_hook(meter)


# --- spend ------------------------------------------------------------------

def spend(db: Session, agency_id, days: int) -> dict:
    """Where the AI spend of the last ``days`` ran: on credit or on the agency's key."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    platform_rows = db.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount_usd), 0), func.count())
        .where(CreditTransaction.agency_id == agency_id, CreditTransaction.kind == "usage", CreditTransaction.created_at >= since)
    ).one()
    platform_usd = -_decimal(platform_rows[0])
    platform_replies = int(platform_rows[1])
    charged = select(CreditTransaction.usage_record_id).where(CreditTransaction.usage_record_id.is_not(None))
    own = db.execute(
        select(UsageRecord.model, UsageRecord.cost_usd, UsageRecord.input_tokens, UsageRecord.output_tokens)
        .where(UsageRecord.agency_id == agency_id, UsageRecord.created_at >= since, UsageRecord.id.not_in(charged))
    ).all()
    own_usd = sum((_decimal(row.cost_usd) if row.cost_usd is not None else list_price(row.model, row.input_tokens, row.output_tokens)) for row in own)
    own_usd = _decimal(own_usd)
    total = platform_usd + own_usd

    def share(value: Decimal) -> int:
        return int((value / total * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if total > 0 else 0

    return {
        "days": days,
        "platform": {"usd": float(platform_usd), "replies": platform_replies, "percent": share(platform_usd)},
        "own": {"usd": float(own_usd), "replies": len(own), "percent": share(own_usd)},
    }


def overview(db: Session, agency: Agency) -> dict:
    settings = get_settings()
    plan = current_plan(agency)
    return {
        "enabled": settings.billing_enabled,
        "plans": [asdict(p) | {"stripe_price_id": None} for p in plans()],
        "plan": asdict(plan) | {"stripe_price_id": None} if plan else None,
        "subscribed": agency.subscription_status in ACTIVE_STATUSES and bool(agency.plan),
        "subscription_status": agency.subscription_status,
        "clients_used": clients_used(db, agency.id),
        "credit_balance": float(balance(agency)),
        "platform_key": bool(settings.billing_platform_key),
        "own_key": _owns_key(db, agency.id, PLATFORM_PROVIDER),
        "topup_amounts": topup_amounts(),
        "topup_bonus_percent": settings.billing_topup_bonus_percent,
        "payments": bool(settings.stripe_secret_key),
        "customer_id": agency.stripe_customer_id,
    }


# --- Stripe -----------------------------------------------------------------

def _flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding: nested keys as a[b][c]."""
    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            pairs.extend(_flatten(value, name))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    pairs.extend(_flatten(item, f"{name}[{index}]"))
                else:
                    pairs.append((f"{name}[{index}]", str(item)))
        elif value is not None:
            pairs.append((name, str(value).lower() if isinstance(value, bool) else str(value)))
    return pairs


async def stripe_post(path: str, data: dict) -> dict:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Payments are not configured on this installation")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{settings.stripe_api_base.rstrip('/')}/{path.lstrip('/')}",
                                     data=_flatten(data), auth=(settings.stripe_secret_key, ""))
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
        raise HTTPException(status_code=502, detail=f"The payment provider refused the request: {message or response.status_code}")
    return body


async def ensure_customer(db: Session, agency: Agency, email: str) -> str:
    if agency.stripe_customer_id:
        return agency.stripe_customer_id
    customer = await stripe_post("customers", {"name": agency.name, "email": email, "metadata": {"agency_id": str(agency.id)}})
    agency.stripe_customer_id = customer["id"]
    db.commit()
    return customer["id"]


async def checkout_plan(db: Session, agency: Agency, email: str, plan: Plan, return_url: str) -> str:
    if not plan.stripe_price_id:
        raise HTTPException(status_code=400, detail="This plan has no price configured for payments")
    customer = await ensure_customer(db, agency, email)
    session = await stripe_post("checkout/sessions", {
        "mode": "subscription", "customer": customer, "client_reference_id": str(agency.id),
        "line_items": [{"price": plan.stripe_price_id, "quantity": 1}],
        "success_url": f"{return_url}?checkout=success", "cancel_url": f"{return_url}?checkout=cancel",
        "metadata": {"agency_id": str(agency.id), "kind": "subscription", "plan": plan.id},
        "subscription_data": {"metadata": {"agency_id": str(agency.id), "plan": plan.id}},
    })
    return session["url"]


async def checkout_topup(db: Session, agency: Agency, email: str, amount: int, return_url: str) -> str:
    if amount not in topup_amounts():
        raise HTTPException(status_code=400, detail="Choose one of the offered amounts")
    customer = await ensure_customer(db, agency, email)
    session = await stripe_post("checkout/sessions", {
        "mode": "payment", "customer": customer, "client_reference_id": str(agency.id),
        "line_items": [{"quantity": 1, "price_data": {"currency": "usd", "unit_amount": amount * 100,
                                                      "product_data": {"name": f"AI credit · USD {amount}"}}}],
        "success_url": f"{return_url}?topup=success", "cancel_url": f"{return_url}?topup=cancel",
        "metadata": {"agency_id": str(agency.id), "kind": "topup", "amount_usd": str(amount)},
    })
    return session["url"]


async def portal(db: Session, agency: Agency, email: str, return_url: str) -> str:
    customer = await ensure_customer(db, agency, email)
    session = await stripe_post("billing_portal/sessions", {"customer": customer, "return_url": return_url})
    return session["url"]


def verify_signature(payload: bytes, header: str | None, secret: str, tolerance: int = 300) -> bool:
    """Stripe's ``Stripe-Signature``: t=<ts>,v1=<hmac-sha256 of "<ts>.<payload>">."""
    if not header or not secret:
        return False
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts.get("t", ["0"])[0])
    except ValueError:
        return False
    if abs(time.time() - timestamp) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in parts.get("v1", []))


def _agency_for(db: Session, obj: dict) -> Agency | None:
    metadata = obj.get("metadata") or {}
    for candidate in (metadata.get("agency_id"), obj.get("client_reference_id")):
        if candidate:
            try:
                agency = db.get(Agency, uuid.UUID(str(candidate)))
            except ValueError:
                agency = None
            if agency:
                return agency
    customer = obj.get("customer")
    if customer:
        return db.scalar(select(Agency).where(Agency.stripe_customer_id == customer))
    return None


def _plan_from_subscription(obj: dict) -> str | None:
    plan_id = (obj.get("metadata") or {}).get("plan")
    if plan_id and plan_by_id(plan_id):
        return plan_id
    for item in ((obj.get("items") or {}).get("data") or []):
        price = (item.get("price") or {}).get("id")
        match = next((p for p in plans() if p.stripe_price_id and p.stripe_price_id == price), None)
        if match:
            return match.id
    return None


def handle_event(db: Session, event: dict) -> str:
    """Apply one webhook event; returns what was done, for the log."""
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    agency = _agency_for(db, obj)
    if agency is None:
        return "ignored: no agency"
    if kind == "checkout.session.completed":
        metadata = obj.get("metadata") or {}
        if obj.get("customer") and not agency.stripe_customer_id:
            agency.stripe_customer_id = obj["customer"]
        if metadata.get("kind") == "topup":
            if obj.get("payment_status") != "paid":
                return "ignored: unpaid"
            amount = _decimal(metadata.get("amount_usd"))
            if amount <= 0:
                return "ignored: no amount"
            try:
                applied = apply_credit(db, agency.id, "topup", amount, "Credit top-up", reference=obj.get("id"))
                bonus_percent = Decimal(str(get_settings().billing_topup_bonus_percent))
                if applied is not None and bonus_percent > 0:
                    apply_credit(db, agency.id, "bonus", amount * bonus_percent / 100, f"Top-up bonus +{bonus_percent.normalize()}%", reference=obj.get("id"))
                db.commit()
            except IntegrityError:
                db.rollback()
                return "duplicate"
            return "topup" if applied is not None else "duplicate"
        if metadata.get("kind") == "subscription":
            agency.plan = metadata.get("plan") or agency.plan
            agency.stripe_subscription_id = obj.get("subscription") or agency.stripe_subscription_id
            agency.subscription_status = "active"
            db.commit()
            return "subscribed"
        return "ignored: checkout kind"
    if kind in ("customer.subscription.created", "customer.subscription.updated"):
        agency.stripe_subscription_id = obj.get("id") or agency.stripe_subscription_id
        agency.subscription_status = str(obj.get("status") or agency.subscription_status)[:30]
        agency.plan = _plan_from_subscription(obj) or agency.plan
        db.commit()
        return f"subscription {agency.subscription_status}"
    if kind == "customer.subscription.deleted":
        agency.subscription_status = "canceled"
        agency.plan = ""
        db.commit()
        return "canceled"
    if kind == "invoice.payment_failed":
        agency.subscription_status = "past_due"
        db.commit()
        return "past_due"
    return "ignored: event type"


def transactions(db: Session, agency_id, limit: int = 50) -> list[CreditTransaction]:
    return list(db.scalars(
        select(CreditTransaction).where(CreditTransaction.agency_id == agency_id)
        .order_by(CreditTransaction.created_at.desc()).limit(max(1, min(limit, 200)))
    ))


def grant(db: Session, agency_id, amount, description: str) -> CreditTransaction | None:
    """A manual credit adjustment by the operator (positive or negative)."""
    transaction = apply_credit(db, agency_id, "adjustment", amount, description or "Manual adjustment")
    db.commit()
    return transaction

