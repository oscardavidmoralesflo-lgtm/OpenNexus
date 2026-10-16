"""Humanized WhatsApp delivery: split replies, typing pace, style mirroring and voice notes."""

import asyncio
import random
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Agent, Conversation, Message, MessageAttachment, WhatsAppChannel
from app.services import humanize
from app.services import whatsapp_inbound as inbound_service

LONG_REPLY = (
    "¡Hola! Claro que sí, con gusto te ayudo con eso.\n\n"
    "El plan básico cuesta 20 dólares al mes e incluye envíos gratis a toda la ciudad.\n\n"
    "Si quieres, te comparto el enlace para pagarlo ahora mismo y lo activamos hoy."
)


# --- pure functions ----------------------------------------------------------

def test_split_by_paragraphs_and_cap():
    assert humanize.split_reply(LONG_REPLY, 3) == [p for p in LONG_REPLY.split("\n\n")]
    two = humanize.split_reply(LONG_REPLY, 2)
    assert len(two) == 2 and "".join(two).replace("\n", "").replace(" ", "") == LONG_REPLY.replace("\n", "").replace(" ", "")


def test_short_replies_and_lists_stay_whole():
    assert humanize.split_reply("Sí, abrimos a las 8.", 3) == ["Sí, abrimos a las 8."]
    menu = "Tenemos estas opciones para ti hoy mismo, todas con envío incluido:\n- Café americano\n- Capuchino con leche de avena\n- Té verde orgánico de la casa"
    assert humanize.split_reply(menu, 3) == [menu]


def test_one_long_paragraph_is_cut_between_sentences():
    text = ("Gracias por escribirnos, revisé tu pedido y ya salió de la bodega esta mañana. "
            "Debería llegarte mañana entre las 9 y las 12 del día. "
            "Si no estás en casa, el repartidor te llamará antes de irse.")
    parts = humanize.split_reply(text, 3)
    assert len(parts) == 3 and all(p.endswith(".") for p in parts)


def test_typing_pace_is_proportional_and_bounded():
    rng = random.Random(1)
    short = humanize.typing_seconds("ok", rng=rng)
    medium = humanize.typing_seconds("x" * 110, rng=rng)
    assert short == humanize.MIN_TYPING
    assert 4 < medium < 6.5
    assert humanize.typing_seconds("x" * 5000, rng=rng) == humanize.MAX_TYPING
    assert humanize.typing_seconds("x" * 100, cps=50, rng=random.Random(1)) < humanize.typing_seconds("x" * 100, cps=10, rng=random.Random(1))


def test_style_mirror_reads_the_customer():
    casual = humanize.style_mirror_prompt(["hola", "cuanto vale el envio 😅", "ok gracias 🙌"], "es")
    assert "cortos" in casual and "emojis con frecuencia" in casual and "informal" in casual
    formal = humanize.style_mirror_prompt(["Buenas tardes. Quisiera saber si ustedes realizan envíos a Medellín y cuál sería el costo aproximado para una caja mediana. Muchas gracias de antemano por su atención, quedo atento a su respuesta."], "es")
    assert "formal" in formal and "No usa emojis" in formal
    assert humanize.style_mirror_prompt([], "es") == ""


def test_speakable_drops_links_and_long_lists():
    assert humanize.speakable("Hola **Ana** 😊, te espero mañana.") == "Hola Ana , te espero mañana."
    assert humanize.speakable("Mira aquí https://example.com") is None
    assert humanize.speakable("Opciones:\n1. A\n2. B\n3. C") is None


# --- delivery ----------------------------------------------------------------

def _setup(client: TestClient, **settings) -> None:
    customer = client.post("/api/clients", json={"name": "Sol Store"}).json()
    client.put("/api/providers/openrouter", json={"api_key": "secret"})
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Sol", "model": "openai/gpt-5.6-luna"}).json()
    assert client.put(f"/api/agents/{agent['id']}/humanization", json=settings).status_code == 200
    assert client.put(f"/api/whatsapp/channels/{customer['id']}", json={"agent_id": agent["id"]}).status_code == 200


def _conversation_with_reply(db, reply: str, *, voice_from_customer: bool = False):
    channel = db.scalar(select(WhatsAppChannel))
    conversation = Conversation(agency_id=channel.agency_id, client_id=channel.client_id, agent_id=channel.agent_id,
                                external_chat_id="573001112233@s.whatsapp.net", channel="whatsapp", whatsapp_channel_id=channel.id)
    db.add(conversation)
    db.flush()
    visitor = Message(conversation_id=conversation.id, role="user", content="hola", sender_type="visitor", external_message_id="in-1")
    db.add(visitor)
    db.flush()
    if voice_from_customer:
        db.add(MessageAttachment(message_id=visitor.id, kind="audio", mime="audio/ogg", data=b"OggS", filename="v.ogg"))
    outbound = Message(conversation_id=conversation.id, role="assistant", content=reply, sender_type="ai", sender_name="Sol")
    db.add(outbound)
    db.commit()
    db.refresh(visitor)
    result = inbound_service.InboundResult(accepted=True, reply=reply, conversation_id=conversation.id, outbound_message_id=outbound.id)
    return channel, conversation, result, [visitor]


def _patch_wire(monkeypatch):
    sent = AsyncMock(side_effect=lambda db, conv, text, quoted_external_id=None: f"out-{len(text)}")
    typing = AsyncMock()
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(inbound_service, "send_channel_message", sent)
    monkeypatch.setattr(inbound_service, "signal_channel_read", typing)
    monkeypatch.setattr(inbound_service.asyncio, "sleep", fake_sleep)
    return sent, typing, sleeps


def test_split_reply_goes_out_as_several_messages_with_typing(authenticated_client: TestClient, monkeypatch):
    _setup(authenticated_client, split_replies=True, split_max_parts=3)
    sent, typing, sleeps = _patch_wire(monkeypatch)
    db = SessionLocal()
    try:
        channel, conversation, result, burst = _conversation_with_reply(db, LONG_REPLY)
        asyncio.run(inbound_service._deliver_humanized(db, channel, conversation, result, ["in-1"], burst, typing_since=0.0))
        assert [call.args[2] for call in sent.await_args_list] == LONG_REPLY.split("\n\n")
        assert typing.await_count == 2, "typing shows again before each further message"
        assert len([s for s in sleeps if s > 0]) >= 2
        stored = db.scalars(select(Message).where(Message.conversation_id == conversation.id, Message.role == "assistant")
                            .order_by(Message.created_at)).all()
        assert [m.content for m in stored] == LONG_REPLY.split("\n\n")
        assert all(m.external_message_id for m in stored)
    finally:
        db.close()


def test_split_stops_when_a_person_takes_over(authenticated_client: TestClient, monkeypatch):
    _setup(authenticated_client, split_replies=True)
    sent, typing, _ = _patch_wire(monkeypatch)
    db = SessionLocal()
    try:
        channel, conversation, result, burst = _conversation_with_reply(db, LONG_REPLY)

        async def take_over(*args, **kwargs):
            other = SessionLocal()
            other.get(Conversation, conversation.id).mode = "human"
            other.commit()
            other.close()
        monkeypatch.setattr(inbound_service, "signal_channel_read", AsyncMock(side_effect=take_over))
        asyncio.run(inbound_service._deliver_humanized(db, channel, conversation, result, ["in-1"], burst, typing_since=0.0))
        assert sent.await_count == 1
    finally:
        db.close()


def test_without_humanization_one_message_goes_out(authenticated_client: TestClient, monkeypatch):
    _setup(authenticated_client)
    sent, typing, sleeps = _patch_wire(monkeypatch)
    db = SessionLocal()
    try:
        channel, conversation, result, burst = _conversation_with_reply(db, LONG_REPLY)
        asyncio.run(inbound_service._deliver_humanized(db, channel, conversation, result, ["in-1"], burst, typing_since=0.0))
        assert [call.args[2] for call in sent.await_args_list] == [LONG_REPLY]
        assert typing.await_count == 0 and not [s for s in sleeps if s > 0]
    finally:
        db.close()


def test_voice_note_mirrors_a_customer_who_sent_one(authenticated_client: TestClient, monkeypatch):
    _setup(authenticated_client, voice_replies="mirror", voice_model="openai/gpt-4o-mini-tts", voice_name="nova")
    sent, typing, _ = _patch_wire(monkeypatch)
    media = AsyncMock(return_value="out-voice")
    monkeypatch.setattr(inbound_service, "send_channel_media", media)
    spoken = []

    async def fake_synthesize(base_url, api_key, model, voice, text):
        spoken.append((model, voice, text))
        usage = humanize.Completion(text="", input_tokens=10)
        return b"OggS-voice", "audio/ogg", usage

    monkeypatch.setattr(humanize, "synthesize", fake_synthesize)
    db = SessionLocal()
    try:
        channel, conversation, result, burst = _conversation_with_reply(db, "Claro, te espero mañana a las 10.", voice_from_customer=True)
        asyncio.run(inbound_service._deliver_humanized(db, channel, conversation, result, ["in-1"], burst, typing_since=0.0))
        assert spoken == [("openai/gpt-4o-mini-tts", "nova", "Claro, te espero mañana a las 10.")]
        assert media.await_args.kwargs["kind"] == "audio" and sent.await_count == 0
        outbound = db.get(Message, result.outbound_message_id)
        assert outbound.external_message_id == "out-voice"
        assert [a.kind for a in outbound.attachments] == ["audio"]

        # A customer who writes gets text back.
        channel, conversation, result, burst = _conversation_with_reply(db, "Perfecto, gracias.")
        asyncio.run(inbound_service._deliver_humanized(db, channel, conversation, result, ["in-1"], burst, typing_since=0.0))
        assert sent.await_count == 1
    finally:
        db.close()


def test_voice_falls_back_to_text_when_synthesis_fails(authenticated_client: TestClient, monkeypatch):
    _setup(authenticated_client, voice_replies="always")
    sent, _, _ = _patch_wire(monkeypatch)

    async def broken(*args):
        raise RuntimeError("no such voice")

    monkeypatch.setattr(humanize, "synthesize", broken)
    db = SessionLocal()
    try:
        channel, conversation, result, burst = _conversation_with_reply(db, "Hola, ¿en qué te ayudo?")
        asyncio.run(inbound_service._deliver_humanized(db, channel, conversation, result, ["in-1"], burst, typing_since=0.0))
        assert [call.args[2] for call in sent.await_args_list] == ["Hola, ¿en qué te ayudo?"]
    finally:
        db.close()


def test_settings_round_trip_and_validation(authenticated_client: TestClient):
    customer = authenticated_client.post("/api/clients", json={"name": "Cfg"}).json()
    agent = authenticated_client.post("/api/agents", json={"client_id": customer["id"], "name": "A"}).json()
    base = f"/api/agents/{agent['id']}/humanization"
    assert authenticated_client.get(base).json() == {"split_replies": False, "split_max_parts": 3, "typing_speed_cps": 0,
                                                     "style_mirror": False, "voice_replies": "off", "voice_model": "", "voice_name": ""}
    saved = authenticated_client.put(base, json={"split_replies": True, "style_mirror": True, "voice_replies": "mirror", "voice_name": " nova "}).json()
    assert saved["split_replies"] and saved["style_mirror"] and saved["voice_name"] == "nova"
    assert authenticated_client.put(base, json={"voice_replies": "sometimes"}).status_code == 422
    assert authenticated_client.put(base, json={"split_max_parts": 9}).status_code == 422


def test_style_mirror_reaches_the_prompt(authenticated_client: TestClient, monkeypatch):
    from app.services.ai import Completion
    _setup(authenticated_client, style_mirror=True)
    completion = AsyncMock(return_value=Completion(text="dale!"))
    monkeypatch.setattr(inbound_service, "run_completion", completion)
    db = SessionLocal()
    try:
        channel = db.scalar(select(WhatsAppChannel))
        asyncio.run(inbound_service.process_inbound(
            db, channel, inbound_service.InboundMessage(external_message_id="m1", external_chat_id="573001112233@s.whatsapp.net",
                                                        sender_name="Ana", text="hola cuanto vale 😅"),
            conversation_channel="whatsapp", channel_fk_field="whatsapp_channel_id"))
        system = completion.await_args.args[4][0]["content"]
        assert "ESTILO DEL CLIENTE" in system and "informal" in system
    finally:
        db.close()
