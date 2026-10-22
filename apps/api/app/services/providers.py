"""Agency-scoped credentials for routers and direct AI providers.

Endpoints are fixed here: credentials are never sent to a user-supplied host.
Chat models use each provider's own model IDs, not OpenRouter aliases.
"""

from collections.abc import Callable
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Agent, ProviderCredential
from ..security import decrypt_secret

# A deployment may lend credentials to an agency that has not stored its own
# (a shared key, a trial pool). It registers one function at startup; the
# function is asked only when the agency holds no key of its own or paused the
# one it holds, so a key in use always wins. It returns (base_url, api_key) or None.
CredentialFallback = Callable[[Session, Any, str], "tuple[str, str] | None"]
CredentialProbe = Callable[[Session, Any, str], bool]
_credential_fallback: CredentialFallback | None = None
_credential_available: CredentialProbe | None = None

CredentialSource = Literal["agency", "deployment", "none"]


PROVIDERS: dict[str, dict[str, str]] = {
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1"},
    "anthropic": {"label": "Anthropic (Claude)", "base_url": "https://api.anthropic.com/v1"},
    "google": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1"},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1"},
    "xai": {"label": "xAI (Grok)", "base_url": "https://api.x.ai/v1"},
    "mistral": {"label": "Mistral AI", "base_url": "https://api.mistral.ai/v1"},
    "together": {"label": "Together AI", "base_url": "https://api.together.ai/v1"},
    "fireworks": {"label": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1"},
    "cerebras": {"label": "Cerebras", "base_url": "https://api.cerebras.ai/v1"},
}
SUPPORTED = tuple(PROVIDERS)
DEFAULT_PROVIDER = "openrouter"
PROVIDER_PATTERN = "^(" + "|".join(SUPPORTED) + ")$"
MODEL_VENDORS = {"openai": "openai", "anthropic": "anthropic", "google": "google", "deepseek": "deepseek", "x-ai": "xai", "mistralai": "mistral"}

# Picker seeds; authenticated discovery supplies the models the key can use.
# These are model IDs, never a price table or a claim of account access.
CHAT_MODELS: dict[str, tuple[str, ...]] = {
    "openai": ("gpt-4.1-mini", "gpt-4.1", "gpt-4.1-nano"),
    "anthropic": ("claude-sonnet-4-6", "claude-opus-5-5", "claude-haiku-4-5"),
    "google": ("gemini-3.8-flash", "gemini-3.1-flash-lite"),
    "deepseek": ("deepseek-flash", "deepseek-v4-pro"),
    "groq": ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"),
    "xai": ("grok-4.7",),
    "mistral": ("mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"),
    "together": ("MiniMaxAI/MiniMax-M3", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "fireworks": ("accounts/fireworks/models/llama-v3p3-70b-instruct",),
    "cerebras": ("zai-glm-4.7", "gpt-oss-120b"),
}


def base_url_for(provider: str) -> str:
    return PROVIDERS[provider]["base_url"]


def register_credential_fallback(fallback: CredentialFallback | None, *, available: CredentialProbe | None = None) -> None:
    """Install what answers when an agency has no key of its own; None removes it.

    ``available`` says whether the fallback would answer right now without
    producing the credentials, for ``credential_source`` and the listing; a
    lender that stops lending (a spent allowance, say) is reported as absent
    instead of handing out a key a request would then be refused on. Without
    it, the fallback itself is asked.
    """
    global _credential_fallback, _credential_available
    _credential_fallback = fallback
    _credential_available = available


def _stored(db: Session, agency_id, provider: str) -> ProviderCredential | None:
    return db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.agency_id == agency_id,
            ProviderCredential.provider == provider,
        )
    )


def _in_use(db: Session, agency_id, provider: str) -> ProviderCredential | None:
    """The agency's own key when it answers: stored and not paused. A paused
    key is kept but counts as absent, so the deployment's fallback is asked."""
    credential = _stored(db, agency_id, provider)
    return credential if credential is not None and credential.enabled else None


def credential_source(db: Session, agency_id, provider: str) -> CredentialSource:
    """Where a reply on this provider would get its key from right now."""
    if provider not in PROVIDERS:
        return "none"
    if _in_use(db, agency_id, provider) is not None:
        return "agency"
    if _credential_fallback is None:
        return "none"
    if _credential_available is not None:
        return "deployment" if _credential_available(db, agency_id, provider) else "none"
    return "deployment" if _credential_fallback(db, agency_id, provider) is not None else "none"


def resolve_provider_credentials(db: Session, agency_id, provider: str) -> tuple[str, str] | None:
    """(base_url, api_key) for an agency's provider: its stored key, else what the
    deployment's fallback lends, else None."""
    if provider not in PROVIDERS:
        return None
    credential = _in_use(db, agency_id, provider)
    if credential is not None:
        return base_url_for(provider), decrypt_secret(credential.encrypted_api_key)
    if _credential_fallback is not None:
        return _credential_fallback(db, agency_id, provider)
    return None


def resolve_agent_credentials(db: Session, agent: Agent) -> tuple[str, str] | None:
    """(base_url, api_key) for the agent's provider using the agency's stored key."""
    return resolve_provider_credentials(db, agent.agency_id, agent.provider)


def resolve_model_credentials(db: Session, agency_id, model: str, *, preferred: str = DEFAULT_PROVIDER) -> tuple[str, str, str, str] | None:
    """Resolve a capability model to (provider, base_url, key, upstream_model).

Keep existing routed capability models working. When no router key is
available, a matching direct vendor key can serve the same model. Never send
a vendor's key to another provider. Bare IDs belong to the selected provider.
"""
    model = model.strip()
    vendor, separator, native = model.partition("/")
    # A direct provider can itself use namespaced IDs (Together, Groq, Fireworks).
    if preferred != DEFAULT_PROVIDER:
        credentials = resolve_provider_credentials(db, agency_id, preferred)
        return (preferred, *credentials, model) if credentials else None
    if separator:
        credentials = resolve_provider_credentials(db, agency_id, DEFAULT_PROVIDER)
        if credentials:
            return (DEFAULT_PROVIDER, *credentials, model)
        direct = MODEL_VENDORS.get(vendor)
        credentials = resolve_provider_credentials(db, agency_id, direct) if direct else None
        return (direct, *credentials, native) if credentials else None
    credentials = resolve_provider_credentials(db, agency_id, preferred)
    return (preferred, *credentials, model) if credentials else None


def model_disclosure_provider(db: Session, agency_id, model: str, *, preferred: str = DEFAULT_PROVIDER) -> str:
    """The capability destination without reading or decrypting any secret.

A deployment fallback is conservatively disclosed as routing through its
registered provider. Unconfigured capabilities retain their intended router.
"""
    if preferred != DEFAULT_PROVIDER:
        return preferred
    direct = MODEL_VENDORS.get(model.partition("/")[0])
    if _in_use(db, agency_id, DEFAULT_PROVIDER) or _credential_fallback is not None:
        return DEFAULT_PROVIDER
    if direct and _in_use(db, agency_id, direct):
        return direct
    return DEFAULT_PROVIDER
