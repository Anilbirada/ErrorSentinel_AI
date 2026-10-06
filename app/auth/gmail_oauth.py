from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from google_auth_oauthlib.flow import Flow
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.database.models import AppUser, GmailConnection, GmailOAuthState
from app.database.session import SessionLocal

GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)
LOGIN_SCOPES = ("openid", "email")
STATE_TTL = timedelta(minutes=10)


def oauth_is_configured(settings: Settings) -> bool:
    return settings.google_oauth_ready


def require_oauth_configuration(settings: Settings) -> None:
    if not oauth_is_configured(settings):
        raise HTTPException(
            status_code=503,
            detail="Gmail connection is not configured. Ask the administrator to configure Google OAuth.",
        )


def _client_config(settings: Settings) -> dict[str, Any]:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                settings.google_redirect_uri,
                settings.google_login_redirect_uri,
            ],
        }
    }


def create_flow(
    settings: Settings,
    *,
    redirect_uri: str,
    scopes: tuple[str, ...],
    state: Optional[str] = None,
) -> Flow:
    require_oauth_configuration(settings)
    return Flow.from_client_config(
        _client_config(settings),
        scopes=list(scopes),
        state=state,
        redirect_uri=redirect_uri,
    )


def get_browser_id(request: Request) -> str:
    browser_id = request.session.get("browser_id")
    if not browser_id:
        browser_id = secrets.token_urlsafe(32)
        request.session["browser_id"] = browser_id
    return browser_id


def state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def save_oauth_state(
    db: Session,
    *,
    state: str,
    browser_id: str,
    purpose: str,
    user_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    nonce: Optional[str] = None,
) -> None:
    db.execute(
        delete(GmailOAuthState).where(
            GmailOAuthState.expires_at <= datetime.now(timezone.utc)
        )
    )
    db.add(
        GmailOAuthState(
            state_hash=state_digest(state),
            browser_id=browser_id,
            purpose=purpose,
            user_id=user_id,
            connection_id=connection_id,
            nonce=nonce,
            expires_at=datetime.now(timezone.utc) + STATE_TTL,
        )
    )
    db.commit()


def consume_oauth_state(
    db: Session,
    *,
    state: str,
    browser_id: str,
    expected_purpose: str | tuple[str, ...],
) -> GmailOAuthState:
    now = datetime.now(timezone.utc)
    digest = state_digest(state)
    purposes = (
        (expected_purpose,)
        if isinstance(expected_purpose, str)
        else expected_purpose
    )
    record = db.scalar(
        select(GmailOAuthState).where(
            GmailOAuthState.state_hash == digest,
            GmailOAuthState.browser_id == browser_id,
            GmailOAuthState.purpose.in_(purposes),
            GmailOAuthState.expires_at > now,
            GmailOAuthState.consumed_at.is_(None),
        )
    )
    if record is None:
        raise HTTPException(status_code=400, detail="OAuth request is invalid or expired.")

    result = db.execute(
        update(GmailOAuthState)
        .where(
            GmailOAuthState.state_hash == digest,
            GmailOAuthState.consumed_at.is_(None),
            GmailOAuthState.expires_at > now,
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="OAuth request is invalid or expired.")
    db.commit()
    db.refresh(record)
    return record


def encrypt_credentials(settings: Settings, credentials_json: str) -> str:
    if not settings.token_encryption_key:
        raise HTTPException(
            status_code=503,
            detail="Gmail token encryption is not configured. Ask the administrator to configure TOKEN_ENCRYPTION_KEY.",
        )
    try:
        fernet = Fernet(settings.token_encryption_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise HTTPException(status_code=503, detail="Gmail token encryption is misconfigured.") from exc
    return fernet.encrypt(credentials_json.encode("utf-8")).decode("ascii")


def decrypt_credentials(settings: Settings, encrypted: str) -> str:
    if not settings.token_encryption_key:
        raise RuntimeError("Gmail token encryption is not configured")
    try:
        fernet = Fernet(settings.token_encryption_key.encode("ascii"))
        return fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("Unable to decrypt the Gmail connection credentials") from exc


def authenticated_user(request: Request, db: Optional[Session] = None) -> AppUser:
    session_data = request.scope.get("session")
    user_id = session_data.get("user_id") if session_data is not None else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in with Google to continue.")
    owns_session = db is None
    session = db or SessionLocal()
    try:
        user = session.get(AppUser, user_id)
        if user is None:
            if session_data is not None:
                session_data.clear()
            raise HTTPException(status_code=401, detail="Sign in with Google to continue.")
        return user
    finally:
        if owns_session:
            session.close()


def request_user_id(request: Request) -> Optional[str]:
    session_data = request.scope.get("session")
    if session_data is None:
        return None
    return session_data.get("user_id")


def verify_csrf(request: Request, token: Optional[str]) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Request verification failed. Refresh the page and try again.")


def connection_for_user(
    db: Session,
    *,
    connection_id: str,
    user_id: str,
) -> GmailConnection:
    connection = db.scalar(
        select(GmailConnection).where(
            GmailConnection.id == connection_id,
            GmailConnection.user_id == user_id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Gmail connection not found.")
    return connection
