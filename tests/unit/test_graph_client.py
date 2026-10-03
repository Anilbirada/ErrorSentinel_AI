from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.outlook.graph_client import GraphClient


@pytest.mark.asyncio
async def test_graph_client_uses_access_token_in_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCredential:
        async def get_token(self, scope: str) -> SimpleNamespace:
            assert scope == "https://graph.microsoft.com/.default"
            return SimpleNamespace(token="access-token")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.outlook.graph_client.credential",
        lambda settings: FakeCredential(),
    )
    client = GraphClient(Settings(_env_file=None))
    try:
        assert await client._headers() == {
            "Authorization": "Bearer access-token",
            "Accept": "application/json",
        }
    finally:
        await client.aclose()
