from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import httpx

from app.config import Settings, get_settings
from app.logging.logger import get_logger
from app.models.email import EmailAttachment, EmailMessage
from app.providers.base import EmailProvider

logger = get_logger("graph_provider")


class MicrosoftGraphProvider(EmailProvider):
    """
    Microsoft Graph API Provider for Microsoft 365 / Outlook integration.
    Implements the common EmailProvider contract.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._access_token: Optional[str] = None
        self._client: Optional[httpx.Client] = None

    @property
    def provider_name(self) -> str:
        return "microsoft_graph"

    def authenticate(self) -> bool:
        if not self.settings.graph_ready:
            logger.info(
                "Microsoft Graph credentials not configured. "
                f"Missing: {', '.join(self.settings.missing_graph_settings)}"
            )
            return False

        try:
            import msal

            authority = f"https://login.microsoftonline.com/{self.settings.ms_tenant_id}"
            app = msal.ConfidentialClientApplication(
                client_id=self.settings.ms_client_id,
                client_credential=self.settings.ms_client_secret,
                authority=authority,
            )
            result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

            if "access_token" in result:
                self._access_token = result["access_token"]
                self._client = httpx.Client(
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=30.0,
                )
                logger.info("MicrosoftGraphProvider successfully authenticated.")
                return True
            else:
                error = result.get("error_description", result.get("error", "Unknown MSAL error"))
                logger.error(f"Microsoft Graph authentication failed: {error}")
                return False

        except Exception as e:
            logger.error(f"Error during Microsoft Graph authentication: {str(e)}", exc_info=True)
            return False

    def is_authenticated(self) -> bool:
        return self._access_token is not None and self._client is not None

    def list_messages(
        self,
        query: Optional[str] = None,
        max_results: int = 25,
        since_timestamp: Optional[str] = None,
    ) -> list[EmailMessage]:
        if not self.is_authenticated():
            if not self.authenticate():
                return []

        try:
            mailbox = self.settings.monitor_mailbox
            url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/Inbox/messages"
            params: dict[str, Any] = {
                "$top": max_results,
                "$select": "id,conversationId,from,toRecipients,ccRecipients,subject,receivedDateTime,body,hasAttachments",
                "$expand": "attachments($select=id,name,contentType,size)",
            }
            if since_timestamp:
                params["$filter"] = f"receivedDateTime ge {since_timestamp}"

            response = self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            messages: list[EmailMessage] = []
            for item in data.get("value", []):
                msg = self._parse_graph_message(item)
                if msg:
                    messages.append(msg)

            return messages

        except Exception as e:
            logger.error(f"Failed to list messages from Microsoft Graph: {str(e)}", exc_info=True)
            return []

    def get_message(self, message_id: str) -> Optional[EmailMessage]:
        if not self.is_authenticated():
            if not self.authenticate():
                return None

        try:
            mailbox = self.settings.monitor_mailbox
            url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{message_id}"
            params = {
                "$expand": "attachments",
            }
            response = self._client.get(url, params=params)
            response.raise_for_status()
            return self._parse_graph_message(response.json())

        except Exception as e:
            logger.error(f"Failed to get message {message_id} from Microsoft Graph: {str(e)}", exc_info=True)
            return None

    def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        target_path: Path,
    ) -> Path:
        if not self.is_authenticated():
            if not self.authenticate():
                raise ConnectionError("Microsoft Graph not authenticated")

        try:
            mailbox = self.settings.monitor_mailbox
            url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{message_id}/attachments/{attachment_id}"
            response = self._client.get(url)
            response.raise_for_status()
            att_data = response.json()

            raw_bytes = att_data.get("contentBytes")
            if not raw_bytes:
                raise ValueError(f"Attachment {attachment_id} missing contentBytes")

            decoded = base64.b64decode(raw_bytes)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "wb") as f:
                f.write(decoded)

            return target_path

        except Exception as e:
            logger.error(f"Failed to download attachment {attachment_id} from Graph: {str(e)}", exc_info=True)
            raise

    def send_alert(
        self,
        recipients: list[str],
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
        attachments: Optional[list[Path]] = None,
    ) -> bool:
        if not recipients:
            logger.warning("No recipients specified for Microsoft Graph alert email.")
            return False

        if not self.is_authenticated():
            if not self.authenticate():
                logger.error("Microsoft Graph not authenticated. Alert send aborted.")
                return False

        try:
            sender_mailbox = self.settings.alert_from_mailbox or self.settings.monitor_mailbox
            url = f"https://graph.microsoft.com/v1.0/users/{sender_mailbox}/sendMail"

            to_recipients = [{"emailAddress": {"address": r}} for r in recipients]
            message_payload: dict[str, Any] = {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": body_html,
                },
                "toRecipients": to_recipients,
            }

            if attachments:
                att_list = []
                for p in attachments:
                    if p.exists():
                        with open(p, "rb") as f:
                            encoded_file = base64.b64encode(f.read()).decode("utf-8")
                        att_list.append({
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "name": p.name,
                            "contentBytes": encoded_file,
                        })
                if att_list:
                    message_payload["attachments"] = att_list

            payload = {"message": message_payload, "saveToSentItems": "true"}
            response = self._client.post(url, json=payload)
            if response.status_code in (202, 200, 204):
                logger.info(f"Microsoft Graph alert email sent successfully to {recipients}")
                return True
            else:
                logger.error(f"Microsoft Graph sendMail returned status {response.status_code}: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to send Microsoft Graph alert: {str(e)}", exc_info=True)
            return False

    def _parse_graph_message(self, item: dict[str, Any]) -> Optional[EmailMessage]:
        try:
            msg_id = item.get("id", "")
            subject = item.get("subject", "(No Subject)")
            from_obj = item.get("from", {}).get("emailAddress", {})
            sender = from_obj.get("address", "")
            to_recipients = [
                r.get("emailAddress", {}).get("address", "")
                for r in item.get("toRecipients", [])
                if r.get("emailAddress", {}).get("address")
            ]
            cc_recipients = [
                r.get("emailAddress", {}).get("address", "")
                for r in item.get("ccRecipients", [])
                if r.get("emailAddress", {}).get("address")
            ]
            body_obj = item.get("body", {})
            body_content = body_obj.get("content", "")
            content_type = body_obj.get("contentType", "Text")

            body_html = body_content if content_type.lower() == "html" else ""
            body_text = body_content if content_type.lower() == "text" else ""

            # Parse date
            received_str = item.get("receivedDateTime")
            dt = datetime.now(timezone.utc)
            if received_str:
                try:
                    dt = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            attachments: list[EmailAttachment] = []
            for att in item.get("attachments", []):
                attachments.append(
                    EmailAttachment(
                        attachment_id=att.get("id", ""),
                        filename=att.get("name", "attachment"),
                        mime_type=att.get("contentType", "application/octet-stream"),
                        size=att.get("size", 0),
                    )
                )

            return EmailMessage(
                message_id=msg_id,
                thread_id=item.get("conversationId", ""),
                sender=sender,
                recipients=to_recipients,
                cc=cc_recipients,
                subject=subject,
                timestamp=dt,
                body_text=body_text,
                body_html=body_html,
                has_attachments=item.get("hasAttachments", False) or len(attachments) > 0,
                attachments=attachments,
                provider="microsoft_graph",
                raw_metadata=item,
            )
        except Exception as e:
            logger.error(f"Failed parsing Graph message item: {str(e)}", exc_info=True)
            return None
