"""Fixed-host Composio transport. Never return upstream bodies containing credentials."""

import re
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

BASE_URL = "https://backend.composio.dev/api/v3.1"


def resource_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,180}", value):
        raise HTTPException(502, "Invalid integration service response")
    return value


def trusted_url(value: object, *, mcp: bool = False) -> str:
    if not isinstance(value, str):
        raise HTTPException(502, "Invalid integration service URL")
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(502, "Invalid integration service URL") from exc
    hosts = {"app.composio.dev", "backend.composio.dev"} if mcp else {"connect.composio.dev", "app.composio.dev", "backend.composio.dev"}
    if parsed.scheme != "https" or parsed.hostname not in hosts or port not in (None, 443) or parsed.username or parsed.password:
        raise HTTPException(502, "Unexpected integration service URL")
    if mcp and not parsed.path.endswith("/mcp"):
        raise HTTPException(502, "Unexpected integration MCP URL")
    return value


async def request(key: str, method: str, path: str, *, body: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=35, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers={"x-api-key": key}, json=body)
        if response.status_code in (401, 403):
            raise HTTPException(409, "Composio rejected the project key or its permissions. Review integration settings.")
        if response.status_code == 404:
            raise HTTPException(409, "This integration or account is unavailable in your Composio project.")
        if response.status_code == 429:
            raise HTTPException(503, "Composio rate limit reached. Try again shortly.")
        if response.is_error or response.is_redirect:
            raise HTTPException(502, "Composio could not complete this step. Check the toolkit configuration in your Composio dashboard.")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        return data
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "The integration service is unavailable or returned an invalid response.") from exc


def session_config(scope: str, slug: str, auth_config_id: str, account_id: str) -> dict:
    return {
        "user_id": scope,
        "toolkits": {"enable": [slug]},
        "auth_configs": {slug: auth_config_id},
        "connected_accounts": {slug: [account_id]},
        "instant": False,
        "manage_connections": {"enable": False},
        "workbench": {"enable": False},
        "proxy_execute": {"enable": False},
        "preload": {"tools": "all"},
        "search": {"enable": False},
        "execute": {"enable_multi_execute": False},
    }
