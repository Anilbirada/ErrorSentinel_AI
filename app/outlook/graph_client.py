from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
from azure.identity.aio import ClientSecretCredential

from app.config import Settings
from app.outlook.auth import credential

logger = logging.getLogger(__name__)


class GraphClient:
    base_url = "https://graph.microsoft.com/v1.0"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._credential: ClientSecretCredential | None = None
        self._http = httpx.AsyncClient(timeout=45)

    async def _headers(self) -> dict[str, str]:
        if self._credential is None:
            self._credential = credential(self.settings)
        token = await self._credential.get_token("https://graph.microsoft.com/.default")
        return {"Authorization": f"Bearer {token.token}", "Accept": "application/json"}

    async def aclose(self) -> None:
        try:
            await self._http.aclose()
        finally:
            if self._credential is not None:
                await self._credential.close()

    async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        for attempt in range(4):
            response = await self._http.request(
                method, url, headers=await self._headers(), **kwargs
            )
            if response.status_code not in (429, 500, 502, 503, 504):
                response.raise_for_status()
                return response

            retry_after = response.headers.get("Retry-After")
            try:
                delay = int(retry_after) if retry_after is not None else 2**attempt
            except ValueError:
                delay = 2**attempt
            logger.warning("Graph transient status %s; retrying", response.status_code)
            await asyncio.sleep(min(delay, 30))

        response.raise_for_status()
        return response

    async def messages_since(self, received_after: str | None) -> AsyncIterator[dict]:
        query = {
            "$select": (
                "id,internetMessageId,subject,from,toRecipients,receivedDateTime,"
                "body,hasAttachments"
            ),
            "$orderby": "receivedDateTime asc",
            "$top": "50",
        }
        if received_after:
            query["$filter"] = f"receivedDateTime gt {received_after}"

        mailbox = quote(self.settings.monitor_mailbox, safe="")
        url = f"{self.base_url}/users/{mailbox}/mailFolders/inbox/messages"
        while url:
            data = (await self.request(
                "GET", url, params=query if url.endswith("messages") else None
            )).json()
            for message in data.get("value", []):
                yield message
            url = data.get("@odata.nextLink")
            query = None

    async def attachments(self, message_id: str) -> list[dict]:
        mailbox = quote(self.settings.monitor_mailbox, safe="")
        encoded_message_id = quote(message_id, safe="")
        url = (
            f"{self.base_url}/users/{mailbox}/messages/"
            f"{encoded_message_id}/attachments"
        )
        return (await self.request("GET", url)).json().get("value", [])

    async def send_mail(self, subject: str, html: str) -> None:
        sender = self.settings.alert_from_mailbox or self.settings.monitor_mailbox
        mailbox = quote(sender, safe="")
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html},
                "toRecipients": [
                    {"emailAddress": {"address": address}}
                    for address in self.settings.recipients
                ],
            }
        }
        await self.request(
            "POST", f"{self.base_url}/users/{mailbox}/sendMail", json=payload
        )
