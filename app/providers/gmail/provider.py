from __future__ import annotations

import base64
import email
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import ROOT, Settings, get_settings
from app.logging.logger import get_logger
from app.models.email import EmailAttachment, EmailMessage
from app.providers.base import EmailProvider

logger = get_logger("gmail_provider")


class GmailProvider(EmailProvider):
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._service = None
        self._credentials = None

    @property
    def provider_name(self) -> str:
        return "gmail"

    def authenticate(self) -> bool:
        """
        Authenticate using Google OAuth client credentials and saved token.
        Follows official Google Python Quickstart OAuth flow.
        """
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            scopes = [s.strip() for s in self.settings.gmail_scopes.split(",") if s.strip()]
            cred_file = Path(self.settings.gmail_credentials_file)
            token_file = Path(self.settings.gmail_token_file)

            if not cred_file.is_absolute():
                cred_file = ROOT / cred_file
            if not token_file.is_absolute():
                token_file = ROOT / token_file

            creds = None
            if token_file.exists():
                creds = Credentials.from_authorized_user_file(str(token_file), scopes)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    logger.info("Refreshing expired Gmail OAuth token...")
                    creds.refresh(Request())
                else:
                    if not cred_file.exists():
                        logger.warning(
                            f"Gmail credentials file not found at {cred_file}. "
                            "Please configure GMAIL_CREDENTIALS_FILE or run OAuth setup."
                        )
                        return False
                    logger.info(f"Initiating OAuth flow from {cred_file}...")
                    flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), scopes)
                    creds = flow.run_local_server(port=0)

                # Save token for next run
                token_file.parent.mkdir(parents=True, exist_ok=True)
                with open(token_file, "w", encoding="utf-8") as token_out:
                    token_out.write(creds.to_json())

            self._credentials = creds
            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            logger.info("GmailProvider successfully authenticated.")
            return True

        except Exception as e:
            logger.error(f"Gmail authentication failed: {str(e)}", exc_info=True)
            self._service = None
            return False

    def is_authenticated(self) -> bool:
        return self._service is not None

    def list_messages(
        self,
        query: Optional[str] = None,
        max_results: int = 25,
        since_timestamp: Optional[str] = None,
    ) -> list[EmailMessage]:
        if not self.is_authenticated():
            if not self.authenticate():
                logger.warning("GmailProvider not authenticated. Returning empty message list.")
                return []

        try:
            q = query or ""
            if since_timestamp:
                q = f"{q} after:{since_timestamp}".strip()

            results = (
                self._service.users()
                .messages()
                .list(userId=self.settings.gmail_user, q=q, maxResults=max_results)
                .execute()
            )
            raw_messages = results.get("messages", [])
            messages: list[EmailMessage] = []

            for raw in raw_messages:
                msg_id = raw.get("id")
                if msg_id:
                    msg = self.get_message(msg_id)
                    if msg:
                        messages.append(msg)

            logger.info(f"GmailProvider retrieved {len(messages)} messages (query: '{q}')")
            return messages

        except Exception as e:
            logger.error(f"Failed to list Gmail messages: {str(e)}", exc_info=True)
            return []

    def get_message(self, message_id: str) -> Optional[EmailMessage]:
        if not self.is_authenticated():
            if not self.authenticate():
                return None

        try:
            raw_msg = (
                self._service.users()
                .messages()
                .get(userId=self.settings.gmail_user, id=message_id, format="full")
                .execute()
            )

            payload = raw_msg.get("payload", {})
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

            subject = headers.get("subject", "(No Subject)")
            sender = headers.get("from", "")
            recipients = [r.strip() for r in headers.get("to", "").split(",") if r.strip()]
            cc = [c.strip() for c in headers.get("cc", "").split(",") if c.strip()]
            thread_id = raw_msg.get("threadId", "")

            # Parse date
            date_str = headers.get("date")
            dt = datetime.now(timezone.utc)
            if date_str:
                try:
                    parsed_dt = email.utils.parsedate_to_datetime(date_str)
                    if parsed_dt:
                        dt = parsed_dt
                except Exception:
                    pass

            body_text = ""
            body_html = ""
            attachments: list[EmailAttachment] = []

            def extract_parts(part_node: dict[str, Any]):
                nonlocal body_text, body_html
                mime = part_node.get("mimeType", "")
                filename = part_node.get("filename", "")
                body_info = part_node.get("body", {})

                if filename:
                    # Attachment
                    att_id = body_info.get("attachmentId") or part_node.get("partId", "")
                    size = body_info.get("size", 0)
                    attachments.append(
                        EmailAttachment(
                            attachment_id=att_id,
                            filename=filename,
                            mime_type=mime,
                            size=size,
                        )
                    )
                else:
                    # Body text or html
                    data = body_info.get("data")
                    if data:
                        decoded = base64.urlsafe_b64decode(data.encode("ASCII")).decode("utf-8", errors="replace")
                        if mime == "text/plain":
                            body_text += decoded + "\n"
                        elif mime == "text/html":
                            body_html += decoded + "\n"

                for subpart in part_node.get("parts", []):
                    extract_parts(subpart)

            extract_parts(payload)

            return EmailMessage(
                message_id=message_id,
                thread_id=thread_id,
                sender=sender,
                recipients=recipients,
                cc=cc,
                subject=subject,
                timestamp=dt,
                body_text=body_text.strip(),
                body_html=body_html.strip(),
                labels=raw_msg.get("labelIds", []),
                has_attachments=len(attachments) > 0,
                attachments=attachments,
                provider="gmail",
                raw_metadata={"id": message_id, "snippet": raw_msg.get("snippet", "")},
            )

        except Exception as e:
            logger.error(f"Failed to fetch Gmail message {message_id}: {str(e)}", exc_info=True)
            return None

    def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        target_path: Path,
    ) -> Path:
        if not self.is_authenticated():
            if not self.authenticate():
                raise ConnectionError("GmailProvider not authenticated")

        try:
            att = (
                self._service.users()
                .messages()
                .attachments()
                .get(userId=self.settings.gmail_user, messageId=message_id, id=attachment_id)
                .execute()
            )
            data_str = att.get("data")
            if not data_str:
                raise ValueError(f"Attachment {attachment_id} has no data")

            file_data = base64.urlsafe_b64decode(data_str.encode("ASCII"))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "wb") as f:
                f.write(file_data)

            logger.info(f"Downloaded attachment to {target_path} ({len(file_data)} bytes)")
            return target_path

        except Exception as e:
            logger.error(f"Failed to download Gmail attachment {attachment_id}: {str(e)}", exc_info=True)
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
            logger.warning("No recipients specified for alert email.")
            return False

        if not self.is_authenticated():
            if not self.authenticate():
                logger.error("Cannot send alert: GmailProvider authentication failed.")
                return False

        try:
            msg = MIMEMultipart("mixed")
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject
            msg["From"] = self.settings.gmail_user

            alt_part = MIMEMultipart("alternative")
            if body_text:
                alt_part.attach(MIMEText(body_text, "plain", "utf-8"))
            if body_html:
                alt_part.attach(MIMEText(body_html, "html", "utf-8"))
            msg.attach(alt_part)

            if attachments:
                for att_path in attachments:
                    if att_path.exists():
                        with open(att_path, "rb") as f:
                            part = MIMEApplication(f.read(), Name=att_path.name)
                        part["Content-Disposition"] = f'attachment; filename="{att_path.name}"'
                        msg.attach(part)

            raw_bytes = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            body = {"raw": raw_bytes}

            send_result = (
                self._service.users()
                .messages()
                .send(userId=self.settings.gmail_user, body=body)
                .execute()
            )
            delivered_id = send_result.get("id")
            if delivered_id:
                logger.info(f"Gmail alert successfully sent with ID: {delivered_id}")
                return True
            else:
                logger.error(f"Gmail send returned unexpected response: {send_result}")
                return False

        except Exception as e:
            logger.error(f"Failed to send Gmail alert: {str(e)}", exc_info=True)
            return False
