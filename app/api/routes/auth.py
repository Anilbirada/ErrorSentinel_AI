from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy import func, select

from app.auth.gmail_oauth import (
    GMAIL_SCOPES,
    LOGIN_SCOPES,
    authenticated_user,
    consume_oauth_state,
    connection_for_user,
    create_flow,
    encrypt_credentials,
    get_browser_id,
    require_oauth_configuration,
    save_oauth_state,
    verify_csrf,
)
from app.config import get_settings
from app.database.models import AppUser, GmailConnection
from app.database.session import SessionLocal
from app.logging.logger import get_logger

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = get_logger("oauth")


@router.get("/google/login")
def google_login(request: Request):
    settings = get_settings()
    require_oauth_configuration(settings)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    browser_id = get_browser_id(request)
    flow = create_flow(
        settings,
        redirect_uri=settings.google_login_redirect_uri,
        scopes=LOGIN_SCOPES,
        state=state,
    )
    url, _ = flow.authorization_url(
        access_type="online",
        prompt="select_account",
        nonce=nonce,
    )
    with SessionLocal() as db:
        save_oauth_state(
            db,
            state=state,
            browser_id=browser_id,
            purpose="login",
            nonce=nonce,
        )
    return RedirectResponse(url, status_code=303)


@router.get("/google/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    if error:
        return RedirectResponse("/login?auth=cancelled", status_code=303)
    if not state or not code:
        return RedirectResponse("/login?auth=failed", status_code=303)

    settings = get_settings()
    try:
        with SessionLocal() as db:
            oauth_state = consume_oauth_state(
                db,
                state=state,
                browser_id=get_browser_id(request),
                expected_purpose="login",
            )
            flow = create_flow(
                settings,
                redirect_uri=settings.google_login_redirect_uri,
                scopes=LOGIN_SCOPES,
                state=state,
            )
            flow.fetch_token(code=code)
            claims = id_token.verify_oauth2_token(
                flow.credentials.id_token,
                GoogleRequest(),
                settings.google_client_id,
            )
            if claims.get("nonce") != oauth_state.nonce or not claims.get("email_verified"):
                raise ValueError("Google sign-in response could not be verified")
            user_id = claims.get("sub")
            email = claims.get("email")
            if not user_id or not email:
                raise ValueError("Google sign-in response did not include a verified identity")

            user = db.get(AppUser, user_id)
            now = datetime.now(timezone.utc)
            if user is None:
                user = AppUser(id=user_id, email=email, created_at=now, updated_at=now)
                db.add(user)
            else:
                user.email = email
                user.updated_at = now
            db.commit()
        request.session["user_id"] = user_id
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        return RedirectResponse("/", status_code=303)
    except Exception:
        logger.warning("Google sign-in failed; sensitive OAuth details were omitted.")
        return RedirectResponse("/login?auth=failed", status_code=303)


@router.get("/session")
def session_info(request: Request):
    user = authenticated_user(request)
    return {"email": user.email, "csrf_token": request.session["csrf_token"]}


@router.post("/logout")
def logout(request: Request, x_csrf_token: str | None = Header(default=None)):
    verify_csrf(request, x_csrf_token)
    request.session.clear()
    return {"status": "signed_out"}


@router.post("/gmail/start")
def gmail_start(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
):
    settings = get_settings()
    user = authenticated_user(request)
    verify_csrf(request, x_csrf_token)
    require_oauth_configuration(settings)
    state = secrets.token_urlsafe(32)
    flow = create_flow(
        settings,
        redirect_uri=settings.google_redirect_uri,
        scopes=GMAIL_SCOPES,
        state=state,
    )
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent select_account",
    )
    with SessionLocal() as db:
        save_oauth_state(
            db,
            state=state,
            browser_id=get_browser_id(request),
            purpose="connect",
            user_id=user.id,
        )
    return {"authorization_url": url}


@router.get("/gmail/callback")
def gmail_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    if error:
        return RedirectResponse("/?gmail=cancelled#gmail-connection", status_code=303)
    if not state or not code:
        return RedirectResponse("/?gmail=failed#gmail-connection", status_code=303)

    settings = get_settings()
    try:
        with SessionLocal() as db:
            user = authenticated_user(request, db)
            oauth_state = consume_oauth_state(
                db,
                state=state,
                browser_id=get_browser_id(request),
                expected_purpose=("connect", "reconnect"),
            )
            if oauth_state.user_id != user.id:
                raise HTTPException(status_code=400, detail="OAuth request is invalid or expired.")
            flow = create_flow(
                settings,
                redirect_uri=settings.google_redirect_uri,
                scopes=GMAIL_SCOPES,
                state=state,
            )
            flow.fetch_token(code=code)
            credentials = flow.credentials
            service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
            email = service.users().getProfile(userId="me").execute().get("emailAddress")
            if not email:
                raise ValueError("Gmail profile response did not include an email address")
            encrypted = encrypt_credentials(settings, credentials.to_json())
            now = datetime.now(timezone.utc)
            if oauth_state.connection_id:
                connection = connection_for_user(
                    db,
                    connection_id=oauth_state.connection_id,
                    user_id=user.id,
                )
                duplicate = db.scalar(
                    select(GmailConnection).where(
                        GmailConnection.user_id == user.id,
                        GmailConnection.email == email,
                        GmailConnection.id != connection.id,
                    )
                )
                if duplicate is not None:
                    raise HTTPException(status_code=409, detail="This Gmail account is already connected.")
                connection.email = email
                connection.encrypted_credentials = encrypted
                connection.status = "CONNECTED"
                connection.last_error = None
                connection.updated_at = now
            else:
                connection = db.scalar(
                    select(GmailConnection).where(
                        GmailConnection.user_id == user.id,
                        GmailConnection.email == email,
                    )
                )
                if connection is None:
                    total = db.scalar(
                        select(func.count())
                        .select_from(GmailConnection)
                        .where(GmailConnection.user_id == user.id)
                    ) or 0
                    if total >= settings.gmail_max_connections:
                        raise HTTPException(status_code=409, detail="Gmail connection limit reached.")
                    connection = GmailConnection(
                        user_id=user.id,
                        email=email,
                        encrypted_credentials=encrypted,
                        status="CONNECTED",
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(connection)
                else:
                    connection.encrypted_credentials = encrypted
                    connection.status = "CONNECTED"
                    connection.last_error = None
                    connection.updated_at = now
            db.commit()
        return RedirectResponse("/?gmail=connected#gmail-connection", status_code=303)
    except Exception:
        logger.warning("Gmail OAuth callback failed; sensitive OAuth details were omitted.")
        return RedirectResponse("/?gmail=failed#gmail-connection", status_code=303)


@router.post("/gmail/{connection_id}/reconnect")
def gmail_reconnect(
    connection_id: str,
    request: Request,
    x_csrf_token: str | None = Header(default=None),
):
    user = authenticated_user(request)
    verify_csrf(request, x_csrf_token)
    state = secrets.token_urlsafe(32)
    settings = get_settings()
    flow = create_flow(
        settings,
        redirect_uri=settings.google_redirect_uri,
        scopes=GMAIL_SCOPES,
        state=state,
    )
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent select_account",
    )
    with SessionLocal() as db:
        connection_for_user(db, connection_id=connection_id, user_id=user.id)
        save_oauth_state(
            db,
            state=state,
            browser_id=get_browser_id(request),
            purpose="reconnect",
            user_id=user.id,
            connection_id=connection_id,
        )
    return {"authorization_url": url}


@router.post("/gmail/{connection_id}/disconnect")
def gmail_disconnect(
    connection_id: str,
    request: Request,
    x_csrf_token: str | None = Header(default=None),
):
    user = authenticated_user(request)
    verify_csrf(request, x_csrf_token)
    with SessionLocal() as db:
        connection = connection_for_user(db, connection_id=connection_id, user_id=user.id)
        encrypted = connection.encrypted_credentials
        connection.encrypted_credentials = ""
        connection.status = "DISCONNECTED"
        connection.last_error = None
        connection.updated_at = datetime.now(timezone.utc)
        db.commit()
    try:
        from app.auth.gmail_oauth import decrypt_credentials

        credentials = Credentials.from_authorized_user_info(
            json.loads(decrypt_credentials(get_settings(), encrypted))
        )
        token = credentials.refresh_token or credentials.token
        if token:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": token},
                timeout=5,
            )
    except Exception:
        logger.info("Gmail access revocation could not be confirmed; local credentials were removed.")
    return {"status": "disconnected"}
