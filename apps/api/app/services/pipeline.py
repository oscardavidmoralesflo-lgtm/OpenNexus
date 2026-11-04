"""The sales pipeline: where each contact of a client stands.

Stages are fixed so every agent understands them the same way: ``new``
(no stage stored yet), ``qualified``, ``booked``, ``won`` and ``lost``.
With the client's pipeline on, agents get one built-in tool to move the
contact they are talking to; like the other built-in tools it only records,
and the caller applies the change after the loop. Booking an appointment
moves an early contact to ``booked`` on its own.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Agent, Contact, Conversation, now_utc
from .tools.specs import ToolSpec

STAGES = ("new", "qualified", "booked", "won", "lost")
# What an agent may set: closing a sale is usually the team's call, but an
# agent that takes payment or a firm order may mark it won.
AGENT_STAGES = ("qualified", "booked", "won", "lost")
EARLY = (None, "new", "qualified")
TOOL_NAME = "update_sales_stage"

_RULES = {
    "es": (
        "EMBUDO DE VENTAS: con la herramienta update_sales_stage registras en qué etapa está esta persona. "
        "Etapa actual: {stage}.\n"
        "- qualified: mostró interés real (preguntó precios, disponibilidad o cómo comprar) y encaja con lo que ofrece el negocio.\n"
        "- booked: agendó una cita, visita o llamada.\n"
        "- won: confirmó la compra o el pago.\n"
        "- lost: dijo claramente que no le interesa o compró en otro lado.\n"
        "Úsala solo cuando la conversación lo muestre con claridad, sin mencionarla a la persona."
    ),
    "en": (
        "SALES PIPELINE: with the update_sales_stage tool you record where this person stands. Current stage: {stage}.\n"
        "- qualified: showed real interest (asked about prices, availability or how to buy) and fits what the business offers.\n"
        "- booked: booked an appointment, visit or call.\n"
        "- won: confirmed the purchase or the payment.\n"
        "- lost: clearly said they are not interested or bought elsewhere.\n"
        "Use it only when the conversation clearly shows it, without mentioning it to the person."
    ),
}


@dataclass
class StageChange:
    stage: str
    note: str = ""
    deal_value: float | None = None


@dataclass
class StageChanges:
    changes: list[StageChange] = field(default_factory=list)


def stage_of(contact: Contact | None) -> str:
    return (contact.stage if contact and contact.stage in STAGES else None) or "new"


def set_stage(contact: Contact, stage: str) -> bool:
    """Move a contact; returns whether anything changed."""
    if stage not in STAGES or stage_of(contact) == stage:
        return False
    contact.stage = stage
    contact.stage_changed_at = now_utc()
    return True


def build_stage_spec(db: Session, agent: Agent, conversation: Conversation, holder: StageChanges) -> tuple[ToolSpec | None, str]:
    """The pipeline tool and its prompt, or (None, "") when the client's
    pipeline is off or the conversation has no contact to move."""
    client = agent.client
    contact_id = getattr(conversation, "contact_id", None)
    contact = db.get(Contact, contact_id) if contact_id else None
    if not client or not client.pipeline_enabled:
        return None, ""
    if contact is None and getattr(conversation, "id", None) is not None:
        return None, ""

    def handler(args: dict) -> tuple[str, bool]:
        stage = str(args.get("stage") or "").strip()
        if stage not in AGENT_STAGES:
            return f"stage must be one of: {', '.join(AGENT_STAGES)}", True
        value = args.get("deal_value")
        try:
            value = round(float(value), 2) if value not in (None, "") else None
        except (TypeError, ValueError):
            value = None
        holder.changes.append(StageChange(stage=stage, note=str(args.get("note") or "")[:300], deal_value=value))
        return f"Stage recorded: {stage}. Do not mention it to the person.", False

    spec = ToolSpec(
        name=TOOL_NAME,
        description="Record where this person stands in the sales pipeline.",
        input_schema={"type": "object", "properties": {
            "stage": {"type": "string", "enum": list(AGENT_STAGES)},
            "deal_value": {"type": "number", "description": "What the sale is worth, when the person said it or chose a priced product"},
            "note": {"type": "string", "description": "One short sentence on why"},
        }, "required": ["stage"]},
        handler=handler,
    )
    lang = agent.prompt_language if agent.prompt_language in _RULES else "es"
    return spec, _RULES[lang].format(stage=stage_of(contact))


def apply_stage(db: Session, conversation: Conversation, holder: StageChanges) -> None:
    if not holder.changes or not conversation.contact_id:
        return
    contact = db.get(Contact, conversation.contact_id)
    if contact is None:
        return
    last = holder.changes[-1]
    set_stage(contact, last.stage)
    if last.deal_value is not None and last.deal_value >= 0:
        contact.deal_value = last.deal_value


def after_booking(db: Session, contact_id) -> None:
    """An appointment was booked: an early contact moves to ``booked``."""
    contact = db.get(Contact, contact_id) if contact_id else None
    if contact is not None and contact.stage in EARLY:
        set_stage(contact, "booked")
