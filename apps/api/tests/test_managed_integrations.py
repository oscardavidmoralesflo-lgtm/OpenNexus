import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Agent, AgentTool, ManagedIntegration, ProviderCredential, User
from app.routers import integrations
from app.security import decrypt_secret
from app.services import composio
from app.services.tools.specs import build_tool_specs
from app.services.tools import mcp_client
from conftest import TestingSession, login_legacy_owner


def setup_agent(client):
    customer = client.post("/api/clients", json={"name": "Integration customer"}).json()
    return client.post("/api/agents", json={"client_id": customer["id"], "name": "Assistant", "provider": "openrouter", "model": "openai/gpt-4.1"}).json()["id"]


@pytest.fixture
def service(monkeypatch):
    calls = []
    state = {"scope": "", "active": True, "foreign": False, "url": "https://app.composio.dev/tool_router/v3/trs_test/mcp", "fail_delete": False}

    async def request(key, method, path, *, body=None):
        calls.append((key, method, path, body))
        if path.startswith("/toolkits"):
            return {"items": []}
        if path == "/auth_configs":
            return {"auth_config": {"id": "ac_test"}}
        if path == "/connected_accounts/link":
            state["scope"] = body["user_id"]
            return {"connected_account_id": "ca_test", "redirect_url": "https://connect.composio.dev/link_test"}
        if method == "DELETE":
            if state["fail_delete"]:
                raise HTTPException(502, "Unavailable")
            return {"success": True}
        if path == "/connected_accounts/ca_test":
            return {"user_id": "foreign" if state["foreign"] else state["scope"], "toolkit": {"slug": "gmail"}, "auth_config": {"id": "ac_test"}, "status": "ACTIVE" if state["active"] else "INITIALIZING"}
        if path == "/tool_router/session":
            return {"mcp": {"url": state["url"]}}
        raise AssertionError((method, path))

    monkeypatch.setattr(composio, "request", request)
    discovered = [{"name": "GMAIL_FETCH_EMAILS", "description": "Fetch", "input_schema": {"type": "object"}}, {"name": "COMPOSIO_MULTI_EXECUTE_TOOL", "input_schema": {}}, {"name": "SLACK_SEND_MESSAGE", "input_schema": {}}]
    discover = AsyncMock(return_value=discovered)
    monkeypatch.setattr(integrations, "discover_mcp_tools", discover)
    return state, calls, discover


def connect(client, agent_id):
    assert client.put("/api/integrations/access", json={"api_key": "project-secret"}).status_code == 200
    response = client.post(f"/api/agents/{agent_id}/integrations/gmail/link")
    assert response.status_code == 200, response.text
    return client.post(f"/api/agents/{agent_id}/integrations/gmail/complete")


def test_catalog_and_setup_are_real_and_scoped(authenticated_client):
    client = authenticated_client
    agent_id = setup_agent(client)
    result = client.get(f"/api/agents/{agent_id}/integrations").json()
    assert result["configured"] is False
    assert len(result["catalog"]) == 157
    assert len({item["slug"] for item in result["catalog"]}) == 157
    assert all("testapp" not in item["slug"] for item in result["catalog"])
    assert client.post(f"/api/agents/{agent_id}/integrations/gmail/link").status_code == 409
    assert client.post(f"/api/agents/{agent_id}/integrations/unknown/link").status_code == 404
    login_legacy_owner(client)
    assert client.get(f"/api/agents/{agent_id}/integrations").status_code == 404
    assert client.get("/api/integrations/access").json()["configured"] is False


def test_connection_is_pinned_disabled_and_secret_safe(authenticated_client, service):
    client = authenticated_client
    agent_id = setup_agent(client)
    result = connect(client, agent_id)
    assert result.status_code == 200, result.text
    tool = result.json()
    assert tool["managed"] is True and tool["has_headers"] is True
    assert tool["enabled"] is False and tool["enabled_tools"] == []
    assert [entry["name"] for entry in tool["cached_tools"]] == ["GMAIL_FETCH_EMAILS"]
    assert "project-secret" not in result.text
    state, calls, _ = service
    config = next(body for _, _, path, body in calls if path == "/tool_router/session")
    assert config["user_id"] == state["scope"]
    assert agent_id in state["scope"]
    assert config["toolkits"] == {"enable": ["gmail"]}
    assert config["connected_accounts"] == {"gmail": ["ca_test"]}
    assert config["instant"] is False
    assert all(config[key]["enable"] is False for key in ("manage_connections", "workbench", "proxy_execute", "search"))
    before = len(calls)
    assert client.post(f"/api/agents/{agent_id}/integrations/gmail/complete").json()["id"] == tool["id"]
    assert len(calls) == before
    assert client.post(f"/api/agents/{agent_id}/integrations/gmail/link").status_code == 409
    with TestingSession() as db:
        credential = db.scalar(select(ProviderCredential).where(ProviderCredential.provider == "composio"))
        assert credential.encrypted_api_key != "project-secret"
        assert decrypt_secret(credential.encrypted_api_key) == "project-secret"
        assert build_tool_specs([db.get(AgentTool, uuid.UUID(tool["id"]))]) == []


@pytest.mark.parametrize("failure", ["pending", "foreign", "unsafe_url"])
def test_unverified_or_untrusted_connections_never_attach(authenticated_client, service, failure):
    state, _, discover = service
    state.update(active=failure != "pending", foreign=failure == "foreign")
    if failure == "unsafe_url":
        state["url"] = "https://attacker.example/mcp"
    agent_id = setup_agent(authenticated_client)
    result = connect(authenticated_client, agent_id)
    assert result.status_code == (502 if failure == "unsafe_url" else 409)
    discover.assert_not_awaited()
    assert authenticated_client.get(f"/api/agents/{agent_id}/tools").json() == []


def test_managed_headers_cannot_be_exfiltrated_and_selection_can_change(authenticated_client, service):
    client = authenticated_client
    agent_id = setup_agent(client)
    tool = connect(client, agent_id).json()
    path = f"/api/agents/{agent_id}/tools/{tool['id']}"
    assert client.patch(path, json={"url": "https://attacker.example/mcp"}).status_code == 409
    assert client.patch(path, json={"headers": {}}).status_code == 409
    assert client.post(f"/api/agents/{agent_id}/tools/test-mcp", json={"tool_id": tool["id"], "url": "https://attacker.example/mcp"}).status_code == 409
    assert client.delete(path).status_code == 409
    updated = client.patch(path, json={"name": tool["name"], "url": tool["url"], "transport": "streamable_http", "enabled_tools": ["GMAIL_FETCH_EMAILS"], "enabled": True})
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabled_tools"] == ["GMAIL_FETCH_EMAILS"]
    assert client.put("/api/integrations/access", json={"api_key": "rotated-project-secret"}).status_code == 200
    with TestingSession() as db:
        assert json.loads(decrypt_secret(db.get(AgentTool, uuid.UUID(tool["id"])).encrypted_headers)) == {"x-api-key": "rotated-project-secret"}
    assert client.delete(f"/api/agents/{agent_id}/integrations/gmail").status_code == 204
    assert client.get(f"/api/agents/{agent_id}/tools").json() == []
    assert service[1][-1][2].endswith("?revoke_on_delete=true")


def test_upstream_failure_still_pauses_local_tools(authenticated_client, service):
    client = authenticated_client
    agent_id = setup_agent(client)
    tool = connect(client, agent_id).json()
    client.patch(f"/api/agents/{agent_id}/tools/{tool['id']}", json={"enabled": True})
    service[0]["fail_delete"] = True
    assert client.delete(f"/api/agents/{agent_id}/integrations/gmail").status_code == 502
    assert client.get(f"/api/agents/{agent_id}/tools").json()[0]["enabled"] is False


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_non_managers_cannot_manage_service_access(authenticated_client, service, role):
    client = authenticated_client
    agent_id = setup_agent(client)
    with TestingSession() as db:
        user = db.scalar(select(User))
        user.role = role
        db.commit()
    assert client.get("/api/integrations/access").status_code == 403
    assert client.put("/api/integrations/access", json={"api_key": "project-secret"}).status_code == 403
    assert client.post(f"/api/agents/{agent_id}/integrations/gmail/link").status_code == 403
    assert client.get(f"/api/agents/{agent_id}/integrations").status_code == 200
    assert service[1] == []


def test_transport_redacts_upstream_errors_and_refuses_redirects(monkeypatch):
    real_client = httpx.AsyncClient
    for status in (302, 401, 429, 500):
        transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"error": "secret-OAuth-token"}, headers={"location": "https://attacker.example"}))
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
        with pytest.raises(HTTPException) as error:
            asyncio.run(composio.request("key", "GET", "/toolkits"))
        assert "secret" not in error.value.detail


def test_long_native_tool_names_have_stable_provider_aliases():
    native = "GITHUB_" + "LONG_ACTION_" * 8
    row = AgentTool(type="mcp", name="app_github", cached_tools=[{"name": native, "input_schema": {}}])
    spec = build_tool_specs([row])[0]
    assert len(spec.name) == 64
    assert spec.mcp_tool_name == native
    assert build_tool_specs([row])[0].name == spec.name


@pytest.mark.parametrize("url", ["http://app.composio.dev/mcp", "https://app.composio.dev.attacker.example/mcp", "https://user:password@app.composio.dev/mcp", "https://app.composio.dev:444/mcp"])
def test_project_key_only_reaches_trusted_mcp_hosts(url):
    with pytest.raises(HTTPException):
        composio.trusted_url(url, mcp=True)


def test_mcp_discovery_reads_all_pages(monkeypatch):
    tool = SimpleNamespace(name="GMAIL_FETCH_EMAILS", description="Fetch", inputSchema={}, annotations=None)
    session = SimpleNamespace(list_tools=AsyncMock(side_effect=[SimpleNamespace(tools=[tool], nextCursor="page2"), SimpleNamespace(tools=[SimpleNamespace(**{**vars(tool), "name": "GMAIL_SEND_EMAIL"})], nextCursor=None)]))

    @asynccontextmanager
    async def open_session(*args):
        yield session

    monkeypatch.setattr(mcp_client, "open_mcp_session", open_session)
    result = asyncio.run(mcp_client.discover_mcp_tools("https://app.composio.dev/mcp", "streamable_http", None))
    assert [item["name"] for item in result] == ["GMAIL_FETCH_EMAILS", "GMAIL_SEND_EMAIL"]
    session.list_tools.assert_awaited_with(cursor="page2")
