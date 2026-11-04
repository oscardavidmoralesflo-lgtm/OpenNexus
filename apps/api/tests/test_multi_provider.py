"""Direct-provider contracts, credential isolation and routed capabilities."""

import asyncio
import uuid

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas import AgentCreate, AgentUpdate
from app.services import ai, providers


@pytest.mark.parametrize("provider", providers.SUPPORTED)
def test_agents_accept_every_registered_provider(provider):
    agent = AgentCreate(client_id=uuid.uuid4(), name="Assistant", provider=provider, model="native-model")
    assert agent.provider == provider
    assert AgentUpdate(provider=provider).provider == provider


def test_agents_reject_unregistered_provider():
    with pytest.raises(ValidationError):
        AgentUpdate(provider="untrusted-endpoint")


@pytest.mark.parametrize("provider", providers.SUPPORTED)
def test_provider_credentials_can_be_saved_paused_and_removed(authenticated_client, provider):
    client = authenticated_client
    saved = client.put(f"/api/providers/{provider}", json={"api_key": "private-test-key"})
    assert saved.status_code == 200
    assert saved.json()["configured"]
    assert "private-test-key" not in saved.text
    paused = client.patch(f"/api/providers/{provider}", json={"enabled": False})
    assert paused.status_code == 200
    assert not paused.json()["configured"]
    assert paused.json()["stored"]
    assert client.get(f"/api/providers/{provider}/models").status_code == 409
    assert client.delete(f"/api/providers/{provider}").status_code == 204


def _transport(monkeypatch, responses, requests):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            requests.append((url, kwargs))
            code, body = responses.pop(0)
            return httpx.Response(code, json=body)

        async def get(self, url, **kwargs):
            return await self.post(url, **kwargs)

    monkeypatch.setattr(ai.httpx, "AsyncClient", Client)


@pytest.mark.parametrize("provider", [p for p in providers.SUPPORTED if p != "openrouter"])
def test_direct_requests_do_not_send_router_extensions(monkeypatch, provider):
    requests = []
    _transport(monkeypatch, [(200, {"choices": [{"message": {"content": "Hello"}}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}})], requests)
    result = asyncio.run(ai.chat_completion(provider, providers.base_url_for(provider), "private-key", "native-model", [{"role": "user", "content": "Hello"}], max_tokens=77))
    assert result.text == "Hello"
    payload = requests[0][1]["json"]
    assert "usage" not in payload
    assert payload["max_tokens"] == 77
    assert result.cost_usd is None


def test_reasoning_parameter_retry_retains_output_budget(monkeypatch):
    requests = []
    _transport(monkeypatch, [(400, {"error": {"message": "Unsupported temperature"}}), (200, {"ok": True})], requests)
    asyncio.run(ai._post_json("https://api.openai.com/v1/chat/completions", {}, {"model": "gpt-5", "usage": {"include": True}}, {"temperature": 0.7, "max_tokens": 51}))
    assert requests[0][1]["json"]["max_completion_tokens"] == 51
    assert requests[1][1]["json"]["max_completion_tokens"] == 51
    assert "temperature" not in requests[1][1]["json"]


def test_model_discovery_uses_anthropic_auth_and_filters_nonchat_models(monkeypatch):
    requests = []
    _transport(monkeypatch, [(200, {"data": [{"id": "claude-sonnet-4-6"}, {"id": "embedding-model"}, {"id": "claude-sonnet-4-6"}]})], requests)
    result = asyncio.run(ai.test_provider("anthropic", providers.base_url_for("anthropic"), "private-key"))
    assert result["models"] == ["claude-sonnet-4-6"]
    assert requests[0][1]["headers"]["x-api-key"] == "private-key"
    assert requests[0][1]["headers"]["anthropic-version"] == "2023-06-01"


def test_discovery_does_not_treat_authentication_failure_as_success(monkeypatch):
    _transport(monkeypatch, [(401, {"error": {"message": "Invalid key"}})], [])
    with pytest.raises(HTTPException):
        asyncio.run(ai.test_provider("openai", providers.base_url_for("openai"), "invalid"))


def test_discovery_accepts_mistral_base_models_with_chat_capability(monkeypatch):
    _transport(monkeypatch, [(200, {"data": [
        {"id": "mistral-small-latest", "type": "base", "capabilities": {"completion_chat": True}},
        {"id": "codestral-only", "type": "base", "capabilities": {"completion_chat": False}},
    ]})], [])
    assert asyncio.run(ai.provider_models("mistral", providers.base_url_for("mistral"), "key")) == ["mistral-small-latest"]


def test_direct_tool_round_trip_preserves_reasoning_and_native_ids(monkeypatch):
    from app.services.tools.loop import tool_loop
    from app.services.tools.specs import ToolSpec

    requests = []
    _transport(monkeypatch, [
        (200, {"choices": [{"message": {"content": "", "reasoning_content": "Need the stock tool", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "stock", "arguments": "{}"}}]}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}),
        (200, {"choices": [{"message": {"content": "In stock"}}], "usage": {"prompt_tokens": 20, "completion_tokens": 2}}),
    ], requests)
    spec = ToolSpec("stock", "Check stock", {"type": "object", "properties": {}}, handler=lambda args: ("Available", False))
    result = asyncio.run(tool_loop(providers.base_url_for("deepseek"), "private-key", "deepseek-flash", [{"role": "user", "content": "Is it available?"}], [spec], None, 80))
    assert result.text == "In stock"
    assert result.input_tokens == 30
    assert "usage" not in requests[0][1]["json"]
    assistant = requests[1][1]["json"]["messages"][-2]
    assert assistant["reasoning_content"] == "Need the stock tool"
    assert requests[1][1]["json"]["model"] == "deepseek-flash"


def test_capability_models_fall_back_to_the_matching_vendor_only(monkeypatch):
    monkeypatch.setattr(providers, "resolve_provider_credentials", lambda db, agency, provider: (providers.base_url_for(provider), "openai-key") if provider == "openai" else None)
    resolved = providers.resolve_model_credentials(None, uuid.uuid4(), "openai/text-embedding-3-small")
    assert resolved == ("openai", providers.base_url_for("openai"), "openai-key", "text-embedding-3-small")
    assert providers.resolve_model_credentials(None, uuid.uuid4(), "google/gemini-embedding-2") is None


def test_namespaced_native_model_stays_with_the_selected_provider(monkeypatch):
    monkeypatch.setattr(providers, "resolve_provider_credentials", lambda db, agency, provider: (providers.base_url_for(provider), provider + "-key"))
    resolved = providers.resolve_model_credentials(None, uuid.uuid4(), "new-vendor/new-model", preferred="together")
    assert resolved == ("together", providers.base_url_for("together"), "together-key", "new-vendor/new-model")


def test_unpriced_direct_usage_is_unknown_instead_of_using_router_prices(authenticated_client):
    from sqlalchemy import select
    from app.models import UsageRecord, User, now_utc
    from conftest import TestingSession

    with TestingSession() as db:
        user = db.scalar(select(User))
        db.add(UsageRecord(agency_id=user.agency_id, provider="groq", model="openai/gpt-5.6-luna", input_tokens=1000, output_tokens=1000))
        db.commit()
    day = now_utc().date().isoformat()
    query = f"from={day}&to={day}"
    report = authenticated_client.get(f"/api/reports/costs?{query}").json()
    assert report["totals"]["unpriced_replies"] == 1
    assert report["totals"]["cost_usd"] == 0
    row = authenticated_client.get(f"/api/reports/replies?{query}").json()["items"][0]
    assert row["cost_unknown"] is True
    assert row["estimated"] is False


def test_capability_disclosure_tracks_the_direct_vendor_without_decrypting(authenticated_client, monkeypatch):
    from sqlalchemy import select
    from app.models import User
    from conftest import TestingSession

    authenticated_client.put("/api/providers/openai", json={"api_key": "private-test-key"})
    monkeypatch.setattr(providers, "decrypt_secret", lambda *_: pytest.fail("Disclosure must not decrypt a key"))
    with TestingSession() as db:
        user = db.scalar(select(User))
        assert providers.model_disclosure_provider(db, user.agency_id, "openai/gpt-4.1") == "openai"
