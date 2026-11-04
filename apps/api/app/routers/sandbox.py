"""The sandbox page: its client, its number, and the agents prospects reach by code."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, User, WhatsAppChannel, WhatsAppCloudChannel
from ..schemas import AgentCreate
from ..services import sandbox

router = APIRouter(prefix="/sandbox", tags=["Sandbox"])


class SandboxNumber(BaseModel):
    kind: str
    status: str
    phone_number: str | None
    display_name: str | None


class SandboxAgent(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    model: str
    is_active: bool
    prospects: int
    # A wa.me link that opens the chat with the code already typed, when the
    # number is known.
    share_link: str | None


class SandboxOut(BaseModel):
    client_id: uuid.UUID
    name: str
    number: SandboxNumber | None
    agents: list[SandboxAgent]


class SandboxAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    model: str = ""
    instructions: str = ""
    brief_summary: str = ""
    prompt_language: str = Field(default="es", pattern=r"^(en|es)$")


def _number(db: Session, client_id: uuid.UUID) -> SandboxNumber | None:
    cloud = db.scalar(select(WhatsAppCloudChannel).where(WhatsAppCloudChannel.client_id == client_id).order_by(WhatsAppCloudChannel.created_at).limit(1))
    if cloud:
        return SandboxNumber(kind="whatsapp_cloud", status=cloud.status, phone_number=cloud.phone_number, display_name=cloud.display_name)
    web = db.scalar(select(WhatsAppChannel).where(WhatsAppChannel.client_id == client_id).order_by(WhatsAppChannel.created_at).limit(1))
    if web:
        return SandboxNumber(kind="whatsapp", status=web.status, phone_number=web.phone_number, display_name=web.display_name)
    return None


def _share_link(number: SandboxNumber | None, code: str) -> str | None:
    digits = re.sub(r"\D", "", (number.phone_number or "") if number else "")
    return f"https://wa.me/{digits}?text={code}" if digits else None


def _state(db: Session, user: User) -> SandboxOut:
    client = sandbox.ensure_sandbox_client(db, user.agency)
    sandbox.ensure_codes(db, client)
    number = _number(db, client.id)
    prospects = sandbox.prospects_by_agent(db, client)
    agents = db.scalars(select(Agent).where(Agent.client_id == client.id, Agent.deleted_at.is_(None)).order_by(Agent.created_at)).all()
    return SandboxOut(
        client_id=client.id, name=client.name, number=number,
        agents=[SandboxAgent(
            id=agent.id, name=agent.name, code=agent.sandbox_code or "", model=agent.model, is_active=agent.is_active,
            prospects=prospects.get(agent.id, 0), share_link=_share_link(number, agent.sandbox_code or ""),
        ) for agent in agents],
    )


@router.post("", response_model=SandboxOut)
def open_sandbox(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The sandbox, made the first time it is opened."""
    return _state(db, user)


@router.post("/agents", response_model=SandboxOut, status_code=status.HTTP_201_CREATED)
def create_sandbox_agent(payload: SandboxAgentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from . import agents as agents_router

    client = sandbox.ensure_sandbox_client(db, user.agency)
    # Creating it in the sandbox client gives it its code.
    agents_router.create_agent(AgentCreate(client_id=client.id, **payload.model_dump()), db=db, user=user)
    return _state(db, user)


@router.post("/agents/{agent_id}/code", response_model=SandboxOut)
def regenerate_code(agent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """A new code for an agent; the old one stops working at once."""
    client = sandbox.ensure_sandbox_client(db, user.agency)
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.client_id == client.id, Agent.deleted_at.is_(None)))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found in the sandbox")
    sandbox.assign_code(db, agent)
    db.commit()
    return _state(db, user)
