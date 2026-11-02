"""Python arm of the Tier-1 client bench (CASE-MATRIX.md, amendment of 2 November 2026).

Each case runs the SDK's own authorization flow the way an application does: an httpx2 client
carrying the SDK's ``OAuthClientProvider``, handed to ``streamable_http_client``, and a
``ClientSession.initialize`` that meets a 401. The driver plays the user agent and nothing
else: the redirect handler follows the authorization URL one hop, and the callback handler
returns what the redirect carried (code, state and iss). It decides no outcome; score.py
reads the server's request log.

Usage (inside the container sharing the bench server's network namespace):
    PYTHONPATH=/w/site python driver.py > ../raw/python.jsonl
"""

from __future__ import annotations

import datetime
import importlib.metadata
import json
import pathlib
import urllib.parse
import urllib.request

import anyio
import httpx2
from mcp.client.auth import OAuthClientProvider
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

BENCH = "http://127.0.0.1:8765"
REQUESTED = f"{BENCH}/tenant-a/mcp"
REDIRECT = "http://127.0.0.1:8766/callback"
CASE_TIMEOUT_S = 20


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102 - keep the 302 for the caller
        return None


_opener = urllib.request.build_opener(NoRedirect)


def bench(path: str, method: str = "GET"):
    data = b"" if method == "POST" else None
    req = urllib.request.Request(f"{BENCH}{path}", method=method, data=data)
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read())


class MemoryStorage:
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client: OAuthClientInformationFull | None = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client

    async def set_client_info(self, client_info):
        self.client = client_info


def source_occurrences(needle: str) -> int:
    """Files of the installed packages naming `needle` (the C1 count)."""
    site = pathlib.Path(__file__).resolve().parent / "site"
    return sum(
        1 for pkg in ("mcp", "mcp_types") for p in (site / pkg).rglob("*.py")
        if needle in p.read_text(encoding="utf-8", errors="ignore")
    )


async def run_case() -> dict:
    seen: dict = {"authorization_url": None, "callback": None}

    async def redirect_handler(url: str) -> None:
        # The user agent: request the authorization URL and keep the redirect it answers with.
        seen["authorization_url"] = url
        try:
            _opener.open(url)
        except urllib.error.HTTPError as e:
            seen["callback"] = e.headers.get("location")

    async def callback_handler() -> AuthorizationCodeResult:
        if not seen["callback"]:
            raise RuntimeError("the authorization endpoint answered with no redirect")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(seen["callback"]).query))
        return AuthorizationCodeResult(
            code=q.get("code", ""), state=q.get("state"), iss=q.get("iss"))

    provider = OAuthClientProvider(
        server_url=REQUESTED,
        client_metadata=OAuthClientMetadata(
            client_name="tier1-bench", redirect_uris=[REDIRECT],
            grant_types=["authorization_code", "refresh_token"], response_types=["code"],
            token_endpoint_auth_method="none", scope="mcp",
        ),
        storage=MemoryStorage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    error = None
    try:
        with anyio.fail_after(CASE_TIMEOUT_S):
            async with httpx2.AsyncClient(auth=provider) as http:
                async with streamable_http_client(REQUESTED, http_client=http) as streams:
                    read, write = streams[0], streams[1]
                    async with ClientSession(read, write) as session:
                        await session.initialize()
    except BaseException as e:  # noqa: BLE001 - the SDK's refusal is the observation
        inner = e
        while isinstance(inner, BaseExceptionGroup) and inner.exceptions:
            inner = inner.exceptions[0]
        error = f"{type(inner).__name__}: {inner}"[:300]
    return {**seen, "error": error}


async def main() -> None:
    version = importlib.metadata.version("mcp")
    c1 = source_occurrences("protected_resources")
    for case_id in bench("/__cases"):
        bench(f"/__case?id={case_id}", "POST")
        result = await run_case()
        log = bench("/__log")["log"]
        print(json.dumps({
            "implementation": "python-sdk", "package": "mcp", "version": version, "level": "flow",
            "case_id": case_id, "requested_identifier": REQUESTED,
            "callback_channel": "AuthorizationCodeResult (code, state, iss)",
            "authorization_url": result["authorization_url"], "callback": result["callback"],
            "connect_error": result["error"], "finish_error": None,
            "c1_source_occurrences": c1 if case_id == "C1" else None,
            "log": log, "run_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }), flush=True)


if __name__ == "__main__":
    anyio.run(main)
