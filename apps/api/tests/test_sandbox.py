"""The sandbox number: prospects pick the agent built for them by sending its code."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import get_settings
from app.services import ai as ai_service
from app.services import sandbox as sandbox_service
from app.services import whatsapp_inbound as whatsapp_inbound_service


def _open(client: TestClient) -> dict:
    response = client.post("/api/sandbox")
    assert response.status_code == 200, response.text
    return response.json()


def _agent(client: TestClient, name: str) -> dict:
    state = client.post("/api/sandbox/agents", json={"name": name, "model": "openai/gpt-5.6-luna"}).json()
    return next(agent for agent in state["agents"] if agent["name"] == name)


def test_sandbox_is_made_once_and_flagged(authenticated_client: TestClient):
    first = _open(authenticated_client)
    again = _open(authenticated_client)
    assert first["client_id"] == again["client_id"]
    assert first["name"] == "Agencia Prisma Sandbox"
    assert first["number"] is None and first["agents"] == []
    clients = authenticated_client.get("/api/clients").json()
    assert [c["is_sandbox"] for c in clients] == [True]


def test_agents_get_distinct_codes_that_can_be_rotated(authenticated_client: TestClient):
    _open(authenticated_client)
    luna = _agent(authenticated_client, "Luna")
    sol = _agent(authenticated_client, "Sol")
    assert len(luna["code"]) == 6 and luna["code"] != sol["code"]
    assert set(luna["code"]) <= set(sandbox_service.CODE_ALPHABET)
    rotated = authenticated_client.post(f"/api/sandbox/agents/{luna['id']}/code").json()
    assert next(a for a in rotated["agents"] if a["id"] == luna["id"])["code"] != luna["code"]
    # Agents of other clients never get a sandbox code.
    other = authenticated_client.post("/api/clients", json={"name": "Real Co"}).json()
    plain = authenticated_client.post("/api/agents", json={"client_id": other["id"], "name": "Plain"}).json()
    assert plain["sandbox_code"] is None
    assert authenticated_client.post(f"/api/sandbox/agents/{plain['id']}/code").status_code == 404


def test_code_routes_the_chat_to_its_agent(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    state = _open(client)
    luna = _agent(client, "Luna")
    sol = _agent(client, "Sol")
    client.put("/api/providers/openrouter", json={"api_key": "secret"})
    channel = client.put(f"/api/whatsapp/channels/{state['client_id']}", json={"agent_id": luna["id"]}).json()
    headers = {"X-Bridge-Token": get_settings().whatsapp_bridge_token}
    completion = AsyncMock(return_value=ai_service.Completion(text="AI reply", input_tokens=1, output_tokens=1))
    monkeypatch.setattr(whatsapp_inbound_service, "run_completion", completion)

    def inbound(message_id: str, text: str, chat: str = "573001112233@s.whatsapp.net") -> dict:
        response = client.post(
            f"/api/internal/whatsapp/channels/{channel['id']}/inbound",
            json={"external_message_id": message_id, "remote_jid": chat, "sender_name": "Prospect", "text": text},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return response.json()

    # No code yet: the sandbox explains itself and no AI is called.
    hello = inbound("m1", "Hola")
    assert "código" in hello["reply"] and completion.await_count == 0

    # A code inside a sentence picks the agent, in any case.
    picked = inbound("m2", f"quiero probar {sol['code'].lower()} por favor")
    assert "Sol" in picked["reply"] and completion.await_count == 0
    conversation = client.get(f"/api/conversations/{picked['conversation_id']}").json()
    assert conversation["agent_id"] == sol["id"]

    # From then on the chosen agent answers, not the channel's.
    answered = inbound("m3", "¿Qué venden?")
    assert answered["reply"] == "AI reply" and completion.await_count == 1
    system_prompt = completion.await_args.args[4][0]["content"] if len(completion.await_args.args) > 4 else str(completion.await_args)
    assert "Sol" in system_prompt

    # Another chat is independent.
    other = inbound("m4", "Hola", chat="573009998877@s.whatsapp.net")
    assert "código" in other["reply"]

    # Switching codes switches agents; the page counts prospects per agent.
    switched = inbound("m5", luna["code"])
    assert "Luna" in switched["reply"]
    counts = {a["name"]: a["prospects"] for a in _open(client)["agents"]}
    assert counts == {"Luna": 1, "Sol": 0}


def test_regular_clients_are_untouched(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    customer = client.post("/api/clients", json={"name": "Normal Co"}).json()
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Beto", "model": "openai/gpt-5.6-luna"}).json()
    client.put("/api/providers/openrouter", json={"api_key": "secret"})
    channel = client.put(f"/api/whatsapp/channels/{customer['id']}", json={"agent_id": agent["id"]}).json()
    monkeypatch.setattr(whatsapp_inbound_service, "run_completion", AsyncMock(return_value=ai_service.Completion(text="Hi!")))
    reply = client.post(
        f"/api/internal/whatsapp/channels/{channel['id']}/inbound",
        json={"external_message_id": "x1", "remote_jid": "573001112233@s.whatsapp.net", "sender_name": "Sam", "text": "ABC123 hola"},
        headers={"X-Bridge-Token": get_settings().whatsapp_bridge_token},
    ).json()
    assert reply["reply"] == "Hi!"
