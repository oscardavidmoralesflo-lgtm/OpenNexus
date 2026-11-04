"""Make an agent's WhatsApp replies read and sound like a person's.

Four per-agent settings, all off by default:

* split replies: a long answer goes out as a few short messages, the way
  people write on WhatsApp, cut at paragraphs or sentences, never mid-list;
* typing pace: "typing…" lasts about as long as a person takes to type each
  of those messages;
* style mirroring: the prompt describes how this customer writes (formal or
  casual, short or long, emojis or not) so the agent answers in kind;
* voice notes: the reply is spoken (text-to-speech through the provider's
  ``/audio/speech``) and sent as a WhatsApp voice note, always or only when
  the customer sent one.

Delivery runs on the delayed-reply path, which owns the timing of each send.
"""

from __future__ import annotations

import random
import re
import uuid

import httpx

from ..models import Agent, Message
from .ai import Completion, auth_headers

DEFAULT_CPS = 22.0
MIN_TYPING = 1.2
MAX_TYPING = 8.0
SPLIT_MIN_CHARS = 160
MIN_PART_CHARS = 25
VOICE_MAX_CHARS = 700
DEFAULT_VOICE_MODEL = "openai/gpt-4o-mini-tts"
DEFAULT_VOICE = "nova"

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[¡¿\"'(A-ZÁÉÍÓÚÑ0-9])")
_LIST_LINE = re.compile(r"^\s*([-*•·]|\d+[.)])\s+", re.MULTILINE)
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


# --- splitting --------------------------------------------------------------

def split_reply(text: str, max_parts: int = 3) -> list[str]:
    """Cut ``text`` into at most ``max_parts`` messages a person would send.

    Paragraphs come first; one long paragraph is cut between sentences. A
    paragraph holding a list stays whole, and tiny pieces are merged back.
    """
    text = (text or "").strip()
    max_parts = max(1, min(int(max_parts or 1), 5))
    if max_parts == 1 or len(text) < SPLIT_MIN_CHARS:
        return [text] if text else []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) == 1 and not _LIST_LINE.search(paragraphs[0]):
        paragraphs = [s.strip() for s in _SENTENCE_END.split(paragraphs[0]) if s.strip()]
    if len(paragraphs) <= 1:
        return [text]
    # Merge pieces too small to stand alone into the next one.
    merged: list[str] = []
    for piece in paragraphs:
        if merged and len(merged[-1]) < MIN_PART_CHARS:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    # Then pack into max_parts groups of similar length, keeping order.
    while len(merged) > max_parts:
        sizes = [len(merged[i]) + len(merged[i + 1]) for i in range(len(merged) - 1)]
        i = sizes.index(min(sizes))
        joiner = "\n\n" if "\n" in merged[i] or "\n" in merged[i + 1] or _LIST_LINE.search(merged[i + 1]) else " "
        merged[i:i + 2] = [f"{merged[i]}{joiner}{merged[i + 1]}"]
    return merged


def typing_seconds(text: str, cps: int | float = 0, *, rng: random.Random | None = None) -> float:
    """How long a person takes to type ``text``, with a little natural jitter."""
    rng = rng or random
    speed = float(cps) if cps and cps > 0 else DEFAULT_CPS
    seconds = len(text or "") / speed * rng.uniform(0.85, 1.15)
    return max(MIN_TYPING, min(MAX_TYPING, seconds))


# --- style mirroring --------------------------------------------------------

def style_profile(texts: list[str]) -> dict:
    """What a customer's recent messages say about how they write."""
    texts = [t.strip() for t in texts if t and t.strip()]
    if not texts:
        return {}
    joined = " ".join(texts)
    words = re.findall(r"\w+", joined.lower())
    letters = [t for t in texts if t[:1].isalpha()]
    return {
        "avg_length": sum(len(t) for t in texts) / len(texts),
        "emoji_rate": len(_EMOJI.findall(joined)) / len(texts),
        "formal": any(w in ("usted", "ustedes", "señor", "señora", "cordial", "atentamente", "sir", "madam", "regards") for w in words),
        "lowercase": bool(letters) and sum(1 for t in letters if t[0].islower()) / len(letters) > 0.6,
        "exclamations": joined.count("!") / len(texts) >= 1,
        "no_punctuation": sum(1 for t in texts if t[-1:].isalnum()) / len(texts) > 0.7,
    }


_MIRROR = {
    "es": {
        "intro": "ESTILO DEL CLIENTE (adáptate con naturalidad, sin exagerar ni imitar errores):",
        "short": "- Escribe mensajes cortos: responde en pocas palabras, directo al punto.",
        "long": "- Escribe con detalle: puedes extenderte un poco más y explicar.",
        "emoji": "- Usa emojis con frecuencia: puedes usar alguno de vez en cuando.",
        "no_emoji": "- No usa emojis: evítalos.",
        "formal": "- Trata de usted y es formal: mantén un tono respetuoso y formal.",
        "casual": "- Es informal y cercano: tutéalo y habla relajado, como en un chat.",
        "lowercase": "- Escribe todo en minúscula y sin formalidades: no hace falta ser rígido con la puntuación.",
        "exclamations": "- Es expresivo y entusiasta: puedes mostrar entusiasmo.",
    },
    "en": {
        "intro": "CUSTOMER'S STYLE (adapt naturally, without overdoing it or copying mistakes):",
        "short": "- They write short messages: answer in a few words, straight to the point.",
        "long": "- They write in detail: you can go a little longer and explain.",
        "emoji": "- They use emojis often: you may use one now and then.",
        "no_emoji": "- They do not use emojis: avoid them.",
        "formal": "- They are formal: keep a respectful, formal tone.",
        "casual": "- They are casual and friendly: talk relaxed, like in a chat.",
        "lowercase": "- They write in lowercase, without formality: no need to be strict with punctuation.",
        "exclamations": "- They are expressive and enthusiastic: you can show enthusiasm.",
    },
}


def style_mirror_prompt(texts: list[str], language: str) -> str:
    profile = style_profile(texts)
    if not profile:
        return ""
    lines = _MIRROR.get(language, _MIRROR["es"])
    out = [lines["intro"]]
    out.append(lines["short"] if profile["avg_length"] < 60 else lines["long"] if profile["avg_length"] > 220 else "")
    out.append(lines["emoji"] if profile["emoji_rate"] >= 0.5 else lines["no_emoji"] if profile["emoji_rate"] == 0 else "")
    out.append(lines["formal"] if profile["formal"] else lines["casual"])
    if profile["lowercase"] and profile["no_punctuation"] and not profile["formal"]:
        out.append(lines["lowercase"])
    if profile["exclamations"]:
        out.append(lines["exclamations"])
    return "\n".join(line for line in out if line)


# --- voice notes ------------------------------------------------------------

def customer_sent_voice(burst: list[Message]) -> bool:
    return any(attachment.kind == "audio" for message in burst for attachment in (message.attachments or []))


def wants_voice(agent: Agent, burst: list[Message]) -> bool:
    mode = (agent.voice_replies or "off").lower()
    return mode == "always" or (mode == "mirror" and customer_sent_voice(burst))


def speakable(text: str) -> str | None:
    """The reply as it should be read aloud, or None when it is better as text
    (links, lists, long answers a person would rather read)."""
    text = (text or "").strip()
    if not text or len(text) > VOICE_MAX_CHARS or _URL.search(text) or len(_LIST_LINE.findall(text)) >= 3:
        return None
    text = re.sub(r"[*_~`#>]", "", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip() or None


async def synthesize(base_url: str, api_key: str, model: str, voice: str, text: str) -> tuple[bytes, str, Completion]:
    """Speak ``text`` with the provider's ``/audio/speech``. Returns the audio,
    its type and a usage record (the router reports the cost later by id)."""
    payload = {"model": model or DEFAULT_VOICE_MODEL, "input": text, "voice": voice or DEFAULT_VOICE, "response_format": "opus"}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{base_url.rstrip('/')}/audio/speech", headers=auth_headers(api_key), json=payload)
    if response.status_code >= 400 or not response.content:
        raise RuntimeError(f"speech synthesis failed ({response.status_code}): {response.text[:200]}")
    mime = (response.headers.get("content-type") or "audio/ogg").split(";")[0].strip()
    usage = Completion(text="", input_tokens=max(1, len(text) // 4))
    usage.generation_id = str(response.headers.get("x-generation-id") or "")
    usage.served_by = str(response.headers.get("x-provider-name") or "")
    return response.content, mime, usage


def new_id() -> uuid.UUID:
    return uuid.uuid4()
