"""Managed integration catalog, account authorization and scoped MCP attachment."""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, AgentTool, ManagedIntegration, ProviderCredential, User, now_utc
from ..security import decrypt_secret, encrypt_secret, mask_secret
from ..services import composio
from ..services.tools.mcp_client import discover_mcp_tools
from .agent_tools import _agent, _check_name_free, _out

router = APIRouter(tags=["Managed integrations"])
CATALOG = json.loads((Path(__file__).parent.parent / "integration_catalog.json").read_text(encoding="utf-8"))
BY_SLUG = {item["slug"]: item for item in CATALOG}


class ProjectKey(BaseModel):
    api_key: str = Field(min_length=8, max_length=500)


def _credential(db: Session, user: User) -> ProviderCredential | None:
    return db.scalar(select(ProviderCredential).where(ProviderCredential.agency_id == user.agency_id, ProviderCredential.provider == "composio"))


def _key(db: Session, user: User) -> str:
    credential = _credential(db, user)
    if not credential or not credential.enabled:
        raise HTTPException(409, "Configure Composio in Settings → Integrations first.")
    return decrypt_secret(credential.encrypted_api_key)


def _scope(user: User, agent_id: uuid.UUID) -> str:
    return f"opennexus:{user.agency_id}:{agent_id}"


def _connection(db: Session, agent_id: uuid.UUID, slug: str, *, lock: bool = False) -> ManagedIntegration | None:
    query = select(ManagedIntegration).where(ManagedIntegration.agent_id == agent_id, ManagedIntegration.toolkit == slug)
    return db.scalar(query.with_for_update() if lock else query)


def _catalog_item(slug: str) -> dict:
    if slug not in BY_SLUG:
        raise HTTPException(404, "Unknown integration")
    return BY_SLUG[slug]


@router.get("/integrations/access")
def access(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    credential = _credential(db, user)
    return {"configured": bool(credential and credential.enabled), "api_key_masked": mask_secret(decrypt_secret(credential.encrypted_api_key)) if credential else ""}


@router.put("/integrations/access")
async def save_access(payload: ProjectKey, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    key = payload.api_key.strip()
    if len(key) < 8:
        raise HTTPException(422, "A project API key is required")
    await composio.request(key, "GET", "/toolkits?limit=1")
    credential = _credential(db, user)
    if not credential:
        credential = ProviderCredential(agency_id=user.agency_id, provider="composio", encrypted_api_key=encrypt_secret(key))
        db.add(credential)
    else:
        credential.encrypted_api_key = encrypt_secret(key)
        credential.enabled = True
    # Rotation must update existing attached MCP credentials as well.
    agent_ids = select(Agent.id).where(Agent.agency_id == user.agency_id)
    tool_ids = select(ManagedIntegration.tool_id).where(ManagedIntegration.agent_id.in_(agent_ids))
    for tool in db.scalars(select(AgentTool).where(AgentTool.id.in_(tool_ids))).all():
        composio.trusted_url(tool.url, mcp=True)
        tool.encrypted_headers = encrypt_secret(json.dumps({"x-api-key": key}))
    db.commit()
    return access(db, user)


@router.get("/agents/{agent_id}/integrations")
def catalog(agent_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _agent(db, user, agent_id)
    connections = db.scalars(select(ManagedIntegration).where(ManagedIntegration.agent_id == agent_id)).all()
    return {
        "configured": bool(_credential(db, user) and _credential(db, user).enabled),
        "catalog": CATALOG,
        "connections": [{"toolkit": row.toolkit, "status": row.status, "tool_id": str(row.tool_id) if row.tool_id else None} for row in connections],
    }


@router.post("/agents/{agent_id}/integrations/{slug}/link")
async def link(agent_id: uuid.UUID, slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Lock the agent to serialize account creation for each toolkit.
    _agent(db, user, agent_id)
    db.execute(select(Agent.id).where(Agent.id == agent_id).with_for_update())
    _catalog_item(slug)
    key = _key(db, user)
    row = _connection(db, agent_id, slug)
    if row and row.tool_id:
        raise HTTPException(409, "This account is already attached. Edit its tools or disconnect it first.")
    if not row:
        config = await composio.request(key, "POST", "/auth_configs", body={"toolkit": {"slug": slug}})
        config_id = composio.resource_id(config.get("auth_config", {}).get("id"))
    else:
        config_id = row.auth_config_id
        # Retire abandoned flows before starting another authorization.
        try:
            await composio.request(key, "DELETE", f"/connected_accounts/{composio.resource_id(row.account_id)}")
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
    result = await composio.request(key, "POST", "/connected_accounts/link", body={"auth_config_id": config_id, "user_id": _scope(user, agent_id)})
    redirect_url = composio.trusted_url(result.get("redirect_url"))
    account_id = composio.resource_id(result.get("connected_account_id"))
    if row:
        row.account_id, row.status = account_id, "pending"
    else:
        db.add(ManagedIntegration(agent_id=agent_id, toolkit=slug, auth_config_id=config_id, account_id=account_id, status="pending"))
    db.commit()
    return {"redirect_url": redirect_url}


@router.post("/agents/{agent_id}/integrations/{slug}/complete")
async def complete(agent_id: uuid.UUID, slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _agent(db, user, agent_id)
    item = _catalog_item(slug)
    key = _key(db, user)
    row = _connection(db, agent_id, slug, lock=True)
    if not row:
        raise HTTPException(404, "Start an account connection first")
    if row.tool_id:
        tool = db.get(AgentTool, row.tool_id)
        if tool:
            return _out(tool)
    account = await composio.request(key, "GET", f"/connected_accounts/{composio.resource_id(row.account_id)}")
    if account.get("user_id") != _scope(user, agent_id) or account.get("toolkit", {}).get("slug") != slug or account.get("auth_config", {}).get("id") != row.auth_config_id:
        raise HTTPException(409, "The external account does not belong to this agent's authorization flow.")
    if account.get("status") != "ACTIVE" or account.get("is_disabled"):
        raise HTTPException(409, "The account is not active yet. Complete authorization in the opened page, then check again.")
    session = await composio.request(key, "POST", "/tool_router/session", body=composio.session_config(_scope(user, agent_id), slug, row.auth_config_id, row.account_id))
    url = composio.trusted_url(session.get("mcp", {}).get("url"), mcp=True)
    try:
        discovered = await discover_mcp_tools(url, "streamable_http", {"x-api-key": key})
    except Exception as exc:
        raise HTTPException(502, "The account is authorized, but its tools could not be loaded. Check again shortly.") from exc
    # Only app tools are exposed; generic execution/connection meta tools are excluded.
    discovered = [entry for entry in discovered if entry.get("name", "").upper().startswith(slug.upper() + "_")]
    if not discovered:
        raise HTTPException(502, "This session exposes no tools for the selected integration.")
    name = "app_" + slug[:14].strip("_")
    existing = set(db.scalars(select(AgentTool.name).where(AgentTool.agent_id == agent_id)).all())
    if name in existing:
        name = name[:17].rstrip("_") + "_" + uuid.uuid4().hex[:6]
    _check_name_free(db, agent_id, name)
    tool = AgentTool(agent_id=agent_id, type="mcp", name=name, description=f"{item['name']} account integration", enabled=False, url=url, transport="streamable_http", cached_tools=discovered, tools_cached_at=now_utc(), enabled_tools=[], encrypted_headers=encrypt_secret(json.dumps({"x-api-key": key})))
    db.add(tool)
    db.flush()
    row.tool_id, row.status = tool.id, "connected"
    db.commit()
    return _out(tool)


@router.delete("/agents/{agent_id}/integrations/{slug}", status_code=204)
async def disconnect(agent_id: uuid.UUID, slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _agent(db, user, agent_id)
    row = _connection(db, agent_id, slug, lock=True)
    if not row:
        return Response(status_code=204)
    # Disable locally even if the upstream service cannot revoke access right now.
    tool = db.get(AgentTool, row.tool_id) if row.tool_id else None
    if tool:
        tool.enabled = False
        db.commit()
    await composio.request(_key(db, user), "DELETE", f"/connected_accounts/{composio.resource_id(row.account_id)}?revoke_on_delete=true")
    db.delete(row)
    if tool:
        db.delete(tool)
    db.commit()
    return Response(status_code=204)
