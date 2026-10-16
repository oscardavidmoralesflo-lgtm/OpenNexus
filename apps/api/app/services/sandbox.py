"""The sandbox: one WhatsApp number where each prospect tries the agent built for them.

Every agent of the agency's sandbox client has a short code. A prospect sends
that code to the sandbox number and from then on that agent answers their
chat; another code switches agents. Until a chat sends a code, a fixed
message explains how it works, so a stray message never spends AI credit.
"""

from __future__ import annotations

import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Agency, Agent, Client, Conversation, Message, SandboxSession, now_utc

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LENGTH = 6
_TOKEN = re.compile(r"[A-Za-z0-9]+")

# Fixed replies, in the agent's prompt language (kept in the customer's
# language, like the rest of what the customer reads on WhatsApp).
MESSAGES = {
    "es": {
        "connected": "✅ Ahora hablas con *{agent}*. Escríbele lo que quieras para probarlo.\n\nPara probar otro agente, envía su código.",
        "unknown": "👋 Este es el número de pruebas de *{agency}*.\n\nEnvía el código del agente que quieres probar (por ejemplo: {example}).",
    },
    "en": {
        "connected": "✅ You are now talking to *{agent}*. Write anything to try it.\n\nTo try another agent, send its code.",
        "unknown": "👋 This is *{agency}*'s test number.\n\nSend the code of the agent you want to try (for example: {example}).",
    },
}


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def sandbox_client(db: Session, agency_id) -> Client | None:
    return db.scalar(select(Client).where(Client.agency_id == agency_id, Client.is_sandbox.is_(True)).limit(1))


def ensure_sandbox_client(db: Session, agency: Agency) -> Client:
    """The agency's sandbox client, made the first time it is needed."""
    from ..slugs import unique_slug

    client = sandbox_client(db, agency.id)
    if client:
        return client
    name = f"{agency.name} Sandbox"[:180]
    client = Client(
        agency_id=agency.id, name=name, is_sandbox=True, portal_enabled=False,
        portal_slug=unique_slug(db, Client, "portal_slug", name),
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def assign_code(db: Session, agent: Agent) -> str:
    """Give ``agent`` a code no other agent of its client holds."""
    taken = set(db.scalars(select(Agent.sandbox_code).where(Agent.client_id == agent.client_id, Agent.sandbox_code.is_not(None))))
    code = new_code()
    while code in taken:
        code = new_code()
    agent.sandbox_code = code
    return code


def ensure_codes(db: Session, client: Client) -> None:
    changed = False
    for agent in db.scalars(select(Agent).where(Agent.client_id == client.id, Agent.deleted_at.is_(None), Agent.sandbox_code.is_(None))):
        assign_code(db, agent)
        changed = True
    if changed:
        db.commit()


def _live_agents(db: Session, client: Client) -> list[Agent]:
    return list(db.scalars(
        select(Agent).where(Agent.client_id == client.id, Agent.deleted_at.is_(None), Agent.is_active.is_(True), Agent.sandbox_code.is_not(None))
    ))


def find_code(text: str, agents: list[Agent]) -> Agent | None:
    """The agent whose code appears as a word of ``text`` (any case)."""
    by_code = {agent.sandbox_code.upper(): agent for agent in agents if agent.sandbox_code}
    for token in _TOKEN.findall(text or ""):
        agent = by_code.get(token.upper())
        if agent:
            return agent
    return None


def _language(agent: Agent | None) -> str:
    return agent.prompt_language if agent and agent.prompt_language in MESSAGES else "es"


def _fixed_reply(db: Session, conversation: Conversation, agent: Agent | None, text: str) -> Message:
    message = Message(
        conversation_id=conversation.id, role="assistant", content=text, sender_type="ai",
        sender_name=agent.name if agent else "Sandbox",
    )
    db.add(message)
    conversation.updated_at = now_utc()
    db.commit()
    return message


def route(db: Session, channel, conversation: Conversation, text: str):
    """Pick the agent for a message on the sandbox number.

    Returns an ``InboundResult`` when the sandbox answered by itself (a code
    switched agents, or no agent is chosen yet); None when the chosen agent
    should answer as usual, with ``conversation.agent_id`` already set to it.
    """
    from .whatsapp_inbound import InboundResult

    client = channel.client
    agents = _live_agents(db, client)
    chosen = find_code(text, agents)
    session = db.scalar(select(SandboxSession).where(
        SandboxSession.client_id == client.id, SandboxSession.external_chat_id == conversation.external_chat_id,
    ))
    if chosen:
        if session:
            session.agent_id = chosen.id
            session.updated_at = now_utc()
        else:
            db.add(SandboxSession(client_id=client.id, external_chat_id=conversation.external_chat_id, agent_id=chosen.id))
        conversation.agent_id = chosen.id
        reply = MESSAGES[_language(chosen)]["connected"].format(agent=chosen.name)
        message = _fixed_reply(db, conversation, chosen, reply)
        return InboundResult(accepted=True, reply=reply, conversation_id=conversation.id, mode="ai", outbound_message_id=message.id)

    current = next((agent for agent in agents if session and agent.id == session.agent_id), None)
    if current:
        if conversation.agent_id != current.id:
            conversation.agent_id = current.id
            db.commit()
        return None

    agency = db.get(Agency, client.agency_id)
    example = agents[0].sandbox_code if agents else "ABC123"
    reply = MESSAGES[_language(channel.agent)]["unknown"].format(agency=agency.name if agency else client.name, example=example)
    message = _fixed_reply(db, conversation, None, reply)
    return InboundResult(accepted=True, reply=reply, conversation_id=conversation.id, mode="ai", outbound_message_id=message.id)


def agent_for(channel, conversation: Conversation) -> Agent:
    """The agent that answers ``conversation``: on the sandbox number the one
    its chat chose, everywhere else the channel's own."""
    chosen = conversation.agent if conversation is not None else None
    if (
        chosen is not None and channel.client is not None and channel.client.is_sandbox
        and chosen.client_id == channel.client_id and chosen.deleted_at is None
    ):
        return chosen
    return channel.agent


def prospects_by_agent(db: Session, client: Client) -> dict:
    rows = db.execute(
        select(SandboxSession.agent_id, func.count()).where(SandboxSession.client_id == client.id).group_by(SandboxSession.agent_id)
    ).all()
    return {agent_id: count for agent_id, count in rows}
