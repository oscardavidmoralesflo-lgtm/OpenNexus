"""MCP access for external AI agents: the endpoint they connect to, and the
dashboard's management of their tokens and of what they did."""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import McpActivity, McpToken, User, now_utc
from ..services import mcp_server

# The endpoint MCP clients talk to (Streamable HTTP, stateless, JSON replies).
public_router = APIRouter(prefix="/mcp", tags=["MCP"])
# The dashboard's side: tokens, the activity log, the tool catalog.
router = APIRouter(prefix="/mcp-access", tags=["MCP"])


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Missing, unknown or revoked token"}},
        headers={"WWW-Authenticate": 'Bearer realm="opennexus-mcp"'},
    )


@public_router.post("")
async def mcp_endpoint(request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    token = mcp_server.authenticate(db, authorization)
    if not token:
        return _unauthorized()
    try:
        body = json.loads(await request.body() or b"null")
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    if isinstance(body, list):
        responses = [r for r in [await mcp_server.handle(db, token, item) for item in body] if r is not None]
        return JSONResponse(responses) if responses else Response(status_code=status.HTTP_202_ACCEPTED)
    response = await mcp_server.handle(db, token, body)
    return JSONResponse(response) if response is not None else Response(status_code=status.HTTP_202_ACCEPTED)


@public_router.get("")
def mcp_stream_not_offered():
    # Stateless server: there are no server-initiated messages to stream.
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})


@public_router.delete("")
def mcp_end_session():
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    read_only: bool = False


class TokenOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    read_only: bool
    created_by: str
    created_at: datetime
    last_used_at: datetime | None


class TokenCreated(TokenOut):
    # Shown once; only its hash is stored.
    secret: str


class ActivityOut(BaseModel):
    id: uuid.UUID
    tool: str
    ok: bool
    token_name: str | None
    arguments: dict
    summary: str
    created_at: datetime


class AccessInfo(BaseModel):
    endpoint: str
    tools: list[dict]


def _token_out(token: McpToken) -> dict:
    return {
        "id": token.id, "name": token.name, "prefix": token.prefix, "read_only": token.read_only,
        "created_by": token.user.name if token.user else "", "created_at": token.created_at, "last_used_at": token.last_used_at,
    }


@router.get("", response_model=AccessInfo)
def access_info(user: User = Depends(get_current_user)):
    from ..services.workspace_domain import describe

    base = describe(user.agency).primary_url.rstrip("/") if user.agency else get_settings().frontend_url.rstrip("/")
    return AccessInfo(endpoint=f"{base}/api/mcp", tools=mcp_server.catalog())


@router.get("/tokens", response_model=list[TokenOut])
def list_tokens(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tokens = db.scalars(
        select(McpToken).where(McpToken.agency_id == user.agency_id, McpToken.revoked_at.is_(None)).order_by(McpToken.created_at.desc())
    ).all()
    return [_token_out(token) for token in tokens]


@router.post("/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(payload: TokenCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    secret = mcp_server.new_token_secret()
    token = McpToken(
        agency_id=user.agency_id, user_id=user.id, name=payload.name.strip(), read_only=payload.read_only,
        token_hash=mcp_server.hash_token(secret), prefix=secret[:12],
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return {**_token_out(token), "secret": secret}


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    token = db.scalar(select(McpToken).where(McpToken.id == token_id, McpToken.agency_id == user.agency_id, McpToken.revoked_at.is_(None)))
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    token.revoked_at = now_utc()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/activity", response_model=list[ActivityOut])
def list_activity(limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(McpActivity).where(McpActivity.agency_id == user.agency_id)
        .order_by(McpActivity.created_at.desc()).limit(max(1, min(limit, 200)))
    ).all()
    return [
        {"id": row.id, "tool": row.tool, "ok": row.ok, "token_name": row.token.name if row.token else None,
         "arguments": row.arguments or {}, "summary": row.summary, "created_at": row.created_at}
        for row in rows
    ]
