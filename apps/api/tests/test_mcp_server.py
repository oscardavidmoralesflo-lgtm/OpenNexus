"""The workspace as an MCP server: tokens, the JSON-RPC protocol, tools, the activity log."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.routers import conversations as conversations_router
from app.services import ai as ai_service


def _token(client: TestClient, **extra) -> dict:
    created = client.post("/api/mcp-access/tokens", json={"name": "Claude Code", **extra})
    assert created.status_code == 201, created.text
    return created.json()


def _rpc(client: TestClient, secret: str, method: str, params: dict | None = None, request_id: int = 1):
    return client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        headers={"Authorization": f"Bearer {secret}"},
    )


def _call(client: TestClient, secret: str, tool: str, arguments: dict) -> dict:
    response = _rpc(client, secret, "tools/call", {"name": tool, "arguments": arguments})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_token_is_shown_once_and_stored_hashed(authenticated_client: TestClient):
    token = _token(authenticated_client)
    assert token["secret"].startswith("onx_") and token["prefix"] == token["secret"][:12]
    listed = authenticated_client.get("/api/mcp-access/tokens").json()
    assert [item["id"] for item in listed] == [token["id"]]
    assert "secret" not in listed[0]
    assert listed[0]["created_by"] == "Ana Admin"

    from app.models import McpToken
    from tests.conftest import TestingSession

    with TestingSession() as db:
        stored = db.get(McpToken, __import__("uuid").UUID(token["id"]))
        assert token["secret"] not in stored.token_hash


def test_endpoint_rejects_missing_unknown_and_revoked_tokens(authenticated_client: TestClient):
    assert authenticated_client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    assert _rpc(authenticated_client, "onx_nope", "ping").status_code == 401
    token = _token(authenticated_client)
    assert _rpc(authenticated_client, token["secret"], "ping").status_code == 200
    assert authenticated_client.delete(f"/api/mcp-access/tokens/{token['id']}").status_code == 204
    assert _rpc(authenticated_client, token["secret"], "ping").status_code == 401
    assert authenticated_client.get("/api/mcp-access/tokens").json() == []


def test_handshake_and_tool_listing(authenticated_client: TestClient):
    secret = _token(authenticated_client)["secret"]
    init = _rpc(authenticated_client, secret, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}}).json()
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["serverInfo"]["name"] == "opennexus"
    assert "tools" in init["result"]["capabilities"]
    # A notification gets no body.
    note = authenticated_client.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Authorization": f"Bearer {secret}"})
    assert note.status_code == 202
    names = {tool["name"] for tool in _rpc(authenticated_client, secret, "tools/list").json()["result"]["tools"]}
    assert {"list_clients", "create_agent", "update_agent", "add_knowledge_text", "test_agent"} <= names
    assert _rpc(authenticated_client, secret, "nope").json()["error"]["code"] == -32601


def test_agent_lifecycle_through_tools(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    secret = _token(client)["secret"]
    customer = _call(client, secret, "create_client", {"name": "Cafe Norte"})
    assert customer["isError"] is False
    client_id = customer["structuredContent"]["id"]

    created = _call(client, secret, "create_agent", {"client_id": client_id, "name": "Luna", "model": "openai/gpt-5.6-luna", "instructions": "Sell coffee."})
    agent_id = created["structuredContent"]["id"]
    updated = _call(client, secret, "update_agent", {"agent_id": agent_id, "personality": "Warm and brief"})
    assert updated["structuredContent"]["personality"] == "Warm and brief"

    knowledge = _call(client, secret, "add_knowledge_text", {"agent_id": agent_id, "title": "Menu", "text": "Espresso costs 3 dollars."})
    assert knowledge["structuredContent"]["status"] == "processed"
    _call(client, secret, "add_qa", {"agent_id": agent_id, "question": "Do you open Sundays?", "answer": "Yes, 8 to 2."})
    listed = _call(client, secret, "list_knowledge", {"agent_id": agent_id})["structuredContent"]
    assert listed["documents"][0]["filename"] == "Menu.md" and listed["qa"][0]["answer"] == "Yes, 8 to 2."

    # The same agent shows in the dashboard: one implementation, two doors.
    assert client.get(f"/api/agents/{agent_id}").json()["personality"] == "Warm and brief"

    client.put("/api/providers/openrouter", json={"api_key": "secret"})
    monkeypatch.setattr(conversations_router, "run_completion", AsyncMock(return_value=ai_service.Completion(text="Espresso is 3 dollars.")))
    tested = _call(client, secret, "test_agent", {"agent_id": agent_id, "message": "How much is an espresso?"})["structuredContent"]
    assert tested["reply"] == "Espresso is 3 dollars." and tested["conversation_id"]
    again = _call(client, secret, "test_agent", {"conversation_id": tested["conversation_id"], "message": "Thanks"})["structuredContent"]
    assert again["conversation_id"] == tested["conversation_id"]

    activity = client.get("/api/mcp-access/activity").json()
    assert [row["tool"] for row in activity][:2] == ["test_agent", "test_agent"]
    assert all(row["ok"] for row in activity)
    assert activity[0]["token_name"] == "Claude Code"


def test_errors_are_tool_results_and_logged(authenticated_client: TestClient):
    client = authenticated_client
    secret = _token(client)["secret"]
    missing = _call(client, secret, "get_agent", {"agent_id": "00000000-0000-0000-0000-000000000000"})
    assert missing["isError"] is True
    invalid = _call(client, secret, "create_client", {})
    assert invalid["isError"] is True and "name" in invalid["content"][0]["text"]
    assert _rpc(client, secret, "tools/call", {"name": "nope", "arguments": {}}).json()["error"]["code"] == -32602
    activity = client.get("/api/mcp-access/activity").json()
    assert [row["ok"] for row in activity] == [False, False]


def test_read_only_token_cannot_change_anything(authenticated_client: TestClient):
    client = authenticated_client
    secret = _token(client, read_only=True)["secret"]
    names = {tool["name"] for tool in _rpc(client, secret, "tools/list").json()["result"]["tools"]}
    assert "list_clients" in names and "create_client" not in names
    refused = _call(client, secret, "create_client", {"name": "Nope"})
    assert refused["isError"] is True
    assert client.get("/api/clients").json() == []


def test_access_info_lists_endpoint_and_tools(authenticated_client: TestClient):
    info = authenticated_client.get("/api/mcp-access").json()
    assert info["endpoint"].endswith("/api/mcp")
    assert any(tool["name"] == "test_agent" and tool["writes"] for tool in info["tools"])


def test_text_and_markdown_knowledge_upload(authenticated_client: TestClient):
    client = authenticated_client
    customer = client.post("/api/clients", json={"name": "Docs Co"}).json()
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Doc"}).json()
    uploaded = client.post(f"/api/agents/{agent['id']}/documents", files={"file": ("faq.md", b"# FAQ\nWe ship in 48h.", "text/markdown")})
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["status"] == "processed" and uploaded.json()["character_count"] > 10
    refused = client.post(f"/api/agents/{agent['id']}/documents", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert refused.status_code == 400
