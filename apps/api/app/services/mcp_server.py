"""The workspace as an MCP server, for external AI agents.

Claude Code, Cursor, Codex or any MCP client connects with a personal token
and can do what its owner does in the dashboard: read clients and agents,
create and tune agents, load knowledge, connect tools and rehearse replies.

Every tool calls the dashboard's own route functions as the token's owner, so
the validation, the ownership checks and the side effects (usage records,
embeddings) are exactly the dashboard's: there is no second implementation to
drift. A route's ``HTTPException`` becomes a tool error the agent can read.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Agent, KnowledgeDocument, McpActivity, McpToken, User, now_utc

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "opennexus"
SERVER_VERSION = "0.3.0"
TOKEN_PREFIX = "onx_"
MAX_TEXT_KNOWLEDGE = 400_000
INSTRUCTIONS = (
    "OpenNexus workspace: an agency's clients and the AI agents that answer their customers. "
    "Start with list_clients and list_agents. Agents belong to a client; create one with create_agent, "
    "refine it with update_agent, give it knowledge with add_knowledge_text or add_qa, and check how it "
    "answers with test_agent (each test reply is billed like any other)."
)


# --- tokens -----------------------------------------------------------------

def hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_token_secret() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def authenticate(db: Session, authorization: str | None) -> McpToken | None:
    """The live token a ``Bearer`` header carries, or None."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    secret = authorization[7:].strip()
    if not secret.startswith(TOKEN_PREFIX):
        return None
    token = db.scalar(select(McpToken).where(McpToken.token_hash == hash_token(secret), McpToken.revoked_at.is_(None)))
    if not token or not token.user or token.user.agency_id != token.agency_id:
        return None
    token.last_used_at = now_utc()
    db.commit()
    return token


# --- tool catalog -----------------------------------------------------------

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    run: Callable[[Session, User, dict], Awaitable[Any]]
    # Changes data or spends credit: refused to read-only tokens.
    writes: bool = False


def _uuid(args: dict, key: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(args.get(key, "")))
    except ValueError as exc:
        raise ToolError(f"`{key}` must be an id returned by another tool") from exc


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return json.loads(json.dumps(value, default=str))


async def _call(route: Callable, **kwargs) -> Any:
    result = route(**kwargs)
    return await result if inspect.isawaitable(result) else result


class ToolError(Exception):
    pass


def _agent_brief(agent: Agent) -> dict:
    return {
        "id": str(agent.id), "name": agent.name, "client_id": str(agent.client_id),
        "client": agent.client.name if agent.client else None, "model": agent.model, "is_active": agent.is_active,
    }


async def _list_clients(db: Session, user: User, args: dict):
    from ..routers import clients
    from ..schemas import ClientOut

    rows = await _call(clients.list_clients, db=db, user=user)
    return [
        {k: v for k, v in ClientOut.model_validate(row).model_dump(mode="json").items()
         if k in ("id", "name", "industry", "business_type", "timezone", "is_active", "portal_enabled")}
        for row in rows
    ]


async def _create_client(db: Session, user: User, args: dict):
    from ..routers import clients
    from ..schemas import ClientCreate, ClientOut

    row = await _call(clients.create_client, payload=ClientCreate(**args), db=db, user=user)
    return ClientOut.model_validate(row)


async def _list_agents(db: Session, user: User, args: dict):
    from ..routers import agents

    rows = await _call(agents.list_agents, db=db, user=user)
    client_id = str(args.get("client_id") or "")
    return [_agent_brief(row) for row in rows if not client_id or str(row.client_id) == client_id]


async def _get_agent(db: Session, user: User, args: dict):
    from ..routers import agents
    from ..schemas import AgentOut

    agent_id = _uuid(args, "agent_id")
    agent = await _call(agents.get_agent, agent_id=agent_id, db=db, user=user)
    out = AgentOut.model_validate(agent).model_dump(mode="json")
    if args.get("include_prompt"):
        out["system_prompt"] = (await _call(agents.get_prompt, agent_id=agent_id, db=db, user=user)).prompt
    return out


async def _create_agent(db: Session, user: User, args: dict):
    from ..routers import agents
    from ..schemas import AgentCreate, AgentOut

    agent = await _call(agents.create_agent, payload=AgentCreate(**args), db=db, user=user)
    return AgentOut.model_validate(agent)


async def _update_agent(db: Session, user: User, args: dict):
    from ..routers import agents
    from ..schemas import AgentOut, AgentUpdate

    agent_id = _uuid(args, "agent_id")
    changes = {k: v for k, v in args.items() if k != "agent_id"}
    if not changes:
        raise ToolError("Pass at least one field to change")
    agent = await _call(agents.update_agent, agent_id=agent_id, payload=AgentUpdate(**changes), db=db, user=user)
    return AgentOut.model_validate(agent)


async def _list_knowledge(db: Session, user: User, args: dict):
    from ..routers import agents

    agent_id = _uuid(args, "agent_id")
    documents = await _call(agents.list_documents, agent_id=agent_id, db=db, user=user)
    qa = await _call(agents.list_qa, agent_id=agent_id, db=db, user=user)
    return {
        "documents": _jsonable(documents),
        "qa": [{"id": str(item.id), "question": item.question, "answer": item.answer} for item in qa],
    }


async def _add_knowledge_text(db: Session, user: User, args: dict):
    from ..routers import agents
    from .knowledge import embed_document_chunks

    agent = agents._agent(db, user, _uuid(args, "agent_id"))
    title = str(args.get("title") or "").strip()[:200] or "Notes"
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("`text` is empty")
    if len(text) > MAX_TEXT_KNOWLEDGE:
        raise ToolError(f"`text` exceeds {MAX_TEXT_KNOWLEDGE} characters; split it into several documents")
    filename = title if title.lower().endswith((".txt", ".md")) else f"{title}.md"
    document = KnowledgeDocument(agent_id=agent.id, filename=filename, file_data=text.encode("utf-8"), extracted_text=text, status="processed")
    db.add(document)
    db.commit()
    db.refresh(document)
    try:
        await embed_document_chunks(db, agent, document)
    except Exception:  # noqa: BLE001 - keyword retrieval still works without embeddings
        db.rollback()
    db.refresh(document)
    return agents._document_out(document)


async def _add_qa(db: Session, user: User, args: dict):
    from ..routers import agents
    from ..schemas import QAPairCreate, QAPairOut

    agent_id = _uuid(args, "agent_id")
    payload = QAPairCreate(question=args.get("question", ""), answer=args.get("answer", ""))
    return QAPairOut.model_validate(await _call(agents.create_qa, agent_id=agent_id, payload=payload, db=db, user=user))


async def _list_tools(db: Session, user: User, args: dict):
    from ..routers import agent_tools

    return await _call(agent_tools.list_tools, agent_id=_uuid(args, "agent_id"), db=db, user=user)


async def _connect_tool(db: Session, user: User, args: dict):
    from ..routers import agent_tools
    from ..schemas_tools import AgentToolIn

    payload = TypeAdapter(AgentToolIn).validate_python(args.get("tool") or {})
    return await _call(agent_tools.create_tool, agent_id=_uuid(args, "agent_id"), payload=payload, db=db, user=user)


async def _test_agent(db: Session, user: User, args: dict):
    from ..routers import conversations
    from ..schemas import ConversationCreate, SendMessageRequest

    message = str(args.get("message") or "").strip()
    if not message:
        raise ToolError("`message` is empty")
    if args.get("conversation_id"):
        conversation_id = _uuid(args, "conversation_id")
    else:
        created = await _call(conversations.create_conversation, payload=ConversationCreate(agent_id=_uuid(args, "agent_id")), db=db, user=user)
        conversation_id = created.id
    detail = await _call(conversations.send_message, conversation_id=conversation_id, payload=SendMessageRequest(content=message), db=db, user=user)
    replies = [m for m in detail.messages if m.role == "assistant"]
    last = replies[-1] if replies else None
    return {
        "conversation_id": str(conversation_id),
        "reply": last.content if last else "",
        "sources": _jsonable(last.sources) if last and last.sources else [],
        "tool_calls": _jsonable(last.tool_calls) if last and last.tool_calls else [],
    }


async def _list_models(db: Session, user: User, args: dict):
    from ..routers import catalog

    models = await _call(catalog.list_catalog_models, user=user)
    return [{"id": m["id"], "label": m["label"], "provider": m["provider"], "context_window": m["context_window"]} for m in models]


_ID = {"type": "string", "description": "An id returned by another tool"}
_AGENT_FIELDS = {
    "name": {"type": "string"},
    "instructions": {"type": "string", "description": "What the agent does and how it answers"},
    "personality": {"type": "string", "description": "Tone and voice"},
    "brief_summary": {"type": "string", "description": "What the business is and offers"},
    "brief_products": {"type": "string"},
    "brief_audience": {"type": "string"},
    "brief_policies": {"type": "string"},
    "brief_dos": {"type": "string"},
    "brief_donts": {"type": "string"},
    "model": {"type": "string", "description": "A model id from list_models, e.g. openai/gpt-5.6-luna"},
    "prompt_language": {"type": "string", "enum": ["en", "es"]},
    "temperature": {"type": "number", "minimum": 0, "maximum": 2},
    "max_tokens": {"type": "integer", "minimum": 1, "maximum": 32000},
    "memory_limit": {"type": "integer", "minimum": 0, "maximum": 200},
    "is_active": {"type": "boolean"},
}

TOOLS: list[Tool] = [
    Tool("list_clients", "List the agency's clients (businesses).", {"type": "object", "properties": {}}, _list_clients),
    Tool("create_client", "Create a client (a business the agency serves).", {
        "type": "object", "required": ["name"],
        "properties": {"name": {"type": "string"}, "industry": {"type": "string"}, "business_type": {"type": "string"},
                       "timezone": {"type": "string", "description": "IANA timezone, e.g. America/Bogota"}},
    }, _create_client, writes=True),
    Tool("list_agents", "List AI agents, optionally only those of one client.", {
        "type": "object", "properties": {"client_id": _ID},
    }, _list_agents),
    Tool("get_agent", "Read an agent's full configuration, optionally with the system prompt it runs on.", {
        "type": "object", "required": ["agent_id"],
        "properties": {"agent_id": _ID, "include_prompt": {"type": "boolean"}},
    }, _get_agent),
    Tool("create_agent", "Create an AI agent for a client.", {
        "type": "object", "required": ["client_id", "name"], "properties": {"client_id": _ID, **_AGENT_FIELDS},
    }, _create_agent, writes=True),
    Tool("update_agent", "Change some fields of an agent; the rest stay as they are.", {
        "type": "object", "required": ["agent_id"], "properties": {"agent_id": _ID, **_AGENT_FIELDS},
    }, _update_agent, writes=True),
    Tool("list_knowledge", "List an agent's knowledge documents and question/answer pairs.", {
        "type": "object", "required": ["agent_id"], "properties": {"agent_id": _ID},
    }, _list_knowledge),
    Tool("add_knowledge_text", "Give an agent knowledge from text or Markdown (FAQ, catalog, policies). It is indexed for retrieval.", {
        "type": "object", "required": ["agent_id", "text"],
        "properties": {"agent_id": _ID, "title": {"type": "string"}, "text": {"type": "string"}},
    }, _add_knowledge_text, writes=True),
    Tool("add_qa", "Teach an agent the exact answer to a question.", {
        "type": "object", "required": ["agent_id", "question", "answer"],
        "properties": {"agent_id": _ID, "question": {"type": "string"}, "answer": {"type": "string"}},
    }, _add_qa, writes=True),
    Tool("list_agent_tools", "List the HTTP and MCP tools an agent can call.", {
        "type": "object", "required": ["agent_id"], "properties": {"agent_id": _ID},
    }, _list_tools),
    Tool("connect_tool", "Connect an HTTP endpoint or an MCP server the agent can call while it answers.", {
        "type": "object", "required": ["agent_id", "tool"],
        "properties": {"agent_id": _ID, "tool": {
            "type": "object", "required": ["type", "name", "url"],
            "description": "type 'http' (with http_method, description, body_params, query_params, headers) or 'mcp' (with transport and headers)",
            "properties": {"type": {"type": "string", "enum": ["http", "mcp"]}, "name": {"type": "string"},
                           "url": {"type": "string"}, "description": {"type": "string"}},
        }},
    }, _connect_tool, writes=True),
    Tool("test_agent", "Send a message to an agent as a customer would and read its reply. Pass conversation_id to continue a test conversation. Billed like any reply.", {
        "type": "object", "required": ["message"],
        "properties": {"agent_id": _ID, "conversation_id": _ID, "message": {"type": "string"}},
    }, _test_agent, writes=True),
    Tool("list_models", "List the AI models an agent can run on.", {"type": "object", "properties": {}}, _list_models),
]
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def catalog() -> list[dict]:
    return [{"name": t.name, "description": t.description, "writes": t.writes} for t in TOOLS]


# --- JSON-RPC ---------------------------------------------------------------

def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _summarize(args: dict) -> dict:
    """The arguments as the activity log keeps them: long text cut short."""
    out: dict = {}
    for key, value in list(args.items())[:12]:
        if isinstance(value, str) and len(value) > 160:
            value = value[:157] + "…"
        elif isinstance(value, (dict, list)):
            text = json.dumps(value, default=str)
            value = text if len(text) <= 160 else text[:157] + "…"
        out[key] = value
    return out


def _outcome(tool: str, data: Any) -> str:
    if isinstance(data, list):
        return f"{len(data)} item(s)"
    if isinstance(data, dict):
        for key in ("name", "filename", "question", "conversation_id", "id"):
            if data.get(key):
                return f"{key}: {str(data[key])[:120]}"
    return "ok"


async def call_tool(db: Session, token: McpToken, name: str, args: dict) -> dict:
    tool = TOOLS_BY_NAME.get(name)
    if not tool:
        raise LookupError(name)
    ok, payload, summary = True, None, ""
    try:
        if tool.writes and token.read_only:
            raise ToolError("This token is read-only; create a token with write access to change things")
        payload = _jsonable(await tool.run(db, token.user, args or {}))
        summary = _outcome(name, payload)
    except HTTPException as exc:
        db.rollback()
        ok, summary = False, str(exc.detail)
    except ValidationError as exc:
        db.rollback()
        ok, summary = False, "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
    except ToolError as exc:
        db.rollback()
        ok, summary = False, str(exc)
    db.add(McpActivity(agency_id=token.agency_id, token_id=token.id, tool=name, ok=ok, arguments=_summarize(args or {}), summary=summary[:2000]))
    db.commit()
    if not ok:
        return {"content": [{"type": "text", "text": summary}], "isError": True}
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    result: dict = {"content": [{"type": "text", "text": text}], "isError": False}
    if isinstance(payload, dict):
        result["structuredContent"] = payload
    return result


async def handle(db: Session, token: McpToken, message: dict) -> dict | None:
    """One JSON-RPC message in, its response out (None for a notification)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request")
    request_id = message.get("id")
    method = message["method"]
    params = message.get("params") or {}
    if request_id is None:
        return None  # notifications (initialized, cancelled) need no answer
    if method == "initialize":
        requested = params.get("protocolVersion")
        return _result(request_id, {
            "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        tools = [t for t in TOOLS if not (t.writes and token.read_only)]
        return _result(request_id, {"tools": [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema,
             "annotations": {"readOnlyHint": not t.writes}} for t in tools
        ]})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "arguments must be an object")
        try:
            return _result(request_id, await call_tool(db, token, name, arguments))
        except LookupError:
            return _error(request_id, -32602, f"Unknown tool: {name}")
    return _error(request_id, -32601, f"Method not found: {method}")
