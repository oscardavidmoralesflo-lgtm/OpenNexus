"""The quality lab: test questions per agent, graded runs, isolation."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import agent_tests
from app.services.ai import Completion
from tests.conftest import login_legacy_owner


def _agent(client: TestClient) -> dict:
    customer = client.post("/api/clients", json={"name": "Cafe"}).json()
    client.put("/api/providers/openrouter", json={"api_key": "secret"})
    return client.post("/api/agents", json={"client_id": customer["id"], "provider": "openrouter", "model": "m", "name": "Luna", "is_active": True}).json()


def test_run_grades_each_answer(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    agent = _agent(client)
    base = f"/api/agents/{agent['id']}/tests"
    good = client.post(base, json={"question": "¿Abren el domingo?", "expectation": "Decir que abre de 9 a 14"}).json()
    client.post(base, json={"question": "¿Cuánto cuesta el café?"})
    assert client.get(base).json()["not_run"] == 2

    calls: list[list[dict]] = []

    async def fake(provider, base_url, api_key, model, messages, **kwargs):
        calls.append(messages)
        if messages[0]["content"] == agent_tests.JUDGE_PROMPT:
            passed = "Domingo" in messages[1]["content"]
            return Completion(text='{"score": 90, "reason": "Correcta"}' if passed else 'Claro: {"score": 20, "reason": "Inventó un precio"}', input_tokens=5, output_tokens=5)
        reply = "Domingo de 9 a 14." if "domingo" in messages[-1]["content"] else "Cuesta $3."
        return Completion(text=reply, input_tokens=10, output_tokens=5)

    monkeypatch.setattr(agent_tests, "chat_completion", fake)
    suite = client.post(f"{base}/run").json()
    assert (suite["passed"], suite["failed"], suite["not_run"]) == (1, 1, 0)
    first = next(c for c in suite["cases"] if c["id"] == good["id"])
    assert first["last_answer"] == "Domingo de 9 a 14." and first["last_score"] == 90 and first["last_reason"] == "Correcta"
    assert len(calls) == 4  # an answer and a grade per test

    # Editing a test clears its verdict until it runs again.
    edited = client.patch(f"{base}/{good['id']}", json={"expectation": "Horario del domingo"}).json()
    assert edited["last_passed"] is None
    one = client.post(f"{base}/run", params={"case_id": good["id"]}).json()
    assert one["passed"] == 1 and len(calls) == 6
    assert client.delete(f"{base}/{good['id']}").status_code == 204
    assert len(client.get(base).json()["cases"]) == 1


def test_tests_stay_inside_the_agency(authenticated_client: TestClient):
    agent = _agent(authenticated_client)
    case = authenticated_client.post(f"/api/agents/{agent['id']}/tests", json={"question": "Hola"}).json()
    other = TestClient(app)
    login_legacy_owner(other)
    assert other.get(f"/api/agents/{agent['id']}/tests").status_code == 404
    assert other.delete(f"/api/agents/{agent['id']}/tests/{case['id']}").status_code == 404


def test_unreadable_verdict_fails_the_test():
    assert agent_tests._parse_verdict("no json here") == (0, "The grader returned an answer that could not be read.")
    assert agent_tests._parse_verdict('{"score": 140, "reason": "x"}') == (100, "x")
