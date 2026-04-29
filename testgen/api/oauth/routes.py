"""OAuth 2.1 endpoints: authorize, token, revoke, register.

Route handlers are sync. The router-level ``db_session`` dependency establishes
a session-per-request with automatic commit/rollback. Body extraction (form/JSON)
is handled by async FastAPI dependencies that resolve before the sync handler
is called in the threadpool.
"""

import logging
import secrets
import time
from urllib.parse import urlparse
from uuid import uuid4

from authlib.oauth2.rfc6749 import OAuth2Request
from authlib.oauth2.rfc6749.requests import BasicOAuth2Payload
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from testgen import settings
from testgen.api.deps import db_session
from testgen.api.oauth.login import render_login_page
from testgen.api.oauth.models import OAuth2Client
from testgen.api.oauth.server import TestGenAuthorizationServer
from testgen.common.auth import create_jwt_token, decode_jwt_token, verify_password
from testgen.common.models import get_current_session
from testgen.common.models.user import User

LOG = logging.getLogger("testgen")

OAUTH_SESSION_COOKIE = "dk_oauth_session"

router = APIRouter(prefix="/oauth", tags=["OAuth"], dependencies=[Depends(db_session)])

_server: TestGenAuthorizationServer | None = None


def init_routes(server: TestGenAuthorizationServer) -> None:
    global _server
    _server = server


async def _form_body(request: Request) -> dict:
    """Async dependency: extract form body as dict before the sync handler runs."""
    return dict(await request.form())


async def _json_body(request: Request) -> dict:
    """Async dependency: extract JSON body as dict before the sync handler runs."""
    body = await request.body()
    if not body:
        return {}
    try:
        return await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc


def _build_oauth2_request(request: Request, body: dict | None = None) -> OAuth2Request:
    # Starlette lowercases header names, but authlib expects title-case (e.g. "Authorization").
    # Re-title-case keys so authlib's header lookups work.
    headers = {k.title(): v for k, v in request.headers.items()}
    # Pass body to constructor so request.form works (authlib grant types still use it internally),
    # and also set payload for the newer authlib API.
    oauth2_req = OAuth2Request(
        method=request.method,
        uri=str(request.url),
        body=body or {},
        headers=headers,
    )
    oauth2_req.payload = BasicOAuth2Payload(body or {})
    return oauth2_req


def _get_existing_user(request: Request) -> User | None:
    """Check for an existing session cookie and return the User if valid."""
    token = request.cookies.get(OAUTH_SESSION_COOKIE)
    if not token:
        return None
    try:
        payload = decode_jwt_token(token)
        return User.get(payload["username"])
    except Exception:
        return None


def _get_client_name(client_id: str) -> str:
    """Look up the OAuth client's display name from its metadata."""
    session = get_current_session()
    client = session.scalars(select(OAuth2Client).where(OAuth2Client.client_id == client_id)).first()
    if client:
        return client.client_metadata.get("client_name", "")
    return ""


def _issue_auth_code(request: Request, user: User, body: dict) -> RedirectResponse:
    """Build an OAuth2 authorization response and return the redirect with a session cookie."""
    oauth2_request = _build_oauth2_request(request, body)
    oauth2_request.user = user

    status, payload, headers = _server.create_authorization_response(oauth2_request, grant_user=user)
    headers = dict(headers)  # authlib returns list-of-tuples
    if status == 302:
        response = RedirectResponse(url=headers["Location"], status_code=302)
    else:
        return JSONResponse(content=payload, status_code=status, headers=headers)

    jwt_token = create_jwt_token(user.username, expiry_seconds=86400)
    response.set_cookie(
        key=OAUTH_SESSION_COOKIE,
        value=jwt_token,
        max_age=86400,
        httponly=True,
        samesite="lax",
        secure=settings.BASE_URL.startswith("https"),
        path="/",
    )
    return response


def _security_headers() -> dict[str, str]:
    return {
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'",
    }


@router.get("/authorize")
def authorize_get(
    request: Request,
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(None),
    scope: str = Query(""),
    state: str = Query(None),
    code_challenge: str = Query(None),
    code_challenge_method: str = Query("S256"),
):
    """Show login form for authorization code flow, or skip if already logged in."""
    body = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri or "",
        "scope": scope,
        "state": state or "",
        "code_challenge": code_challenge or "",
        "code_challenge_method": code_challenge_method,
    }

    existing_user = _get_existing_user(request)
    if existing_user:
        return _issue_auth_code(request, existing_user, body)

    client_name = _get_client_name(client_id)

    return HTMLResponse(
        render_login_page(
            client_id=client_id,
            redirect_uri=redirect_uri or "",
            response_type=response_type,
            scope=scope,
            state=state or "",
            code_challenge=code_challenge or "",
            code_challenge_method=code_challenge_method,
            client_name=client_name,
        ),
        headers=_security_headers(),
    )


@router.post("/authorize")
def authorize_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(""),
    response_type: str = Form("code"),
    scope: str = Form(""),
    state: str = Form(""),
    code_challenge: str = Form(""),
    code_challenge_method: str = Form("S256"),
):
    """Authenticate user and issue authorization code."""
    user = User.get(username)
    if not user or not verify_password(password, user.password):
        client_name = _get_client_name(client_id)
        return HTMLResponse(
            render_login_page(
                client_id=client_id,
                redirect_uri=redirect_uri,
                response_type=response_type,
                scope=scope,
                state=state,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                error="Invalid username or password",
                client_name=client_name,
            ),
            status_code=401,
            headers=_security_headers(),
        )

    body = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    }
    return _issue_auth_code(request, user, body)


@router.get("/logout")
def logout(request: Request, redirect_uri: str = Query("/")):
    """Clear the OAuth session cookie and redirect.

    Enforces same-origin on redirect_uri to prevent open redirect attacks.
    """
    parsed = urlparse(redirect_uri)
    if parsed.netloc and parsed.netloc != request.url.netloc:
        redirect_uri = "/"
    response = RedirectResponse(url=redirect_uri, status_code=302)
    response.delete_cookie(key=OAUTH_SESSION_COOKIE, path="/")
    return response


@router.post("/token")
def token(request: Request, body: dict = Depends(_form_body)):  # noqa: B008
    """Exchange credentials or authorization code for an access token."""
    oauth2_request = _build_oauth2_request(request, body)
    status, payload, headers = _server.create_token_response(oauth2_request)
    return JSONResponse(content=payload, status_code=status, headers=dict(headers))


@router.post("/revoke")
def revoke(request: Request, body: dict = Depends(_form_body)):  # noqa: B008
    """Revoke an access or refresh token."""
    oauth2_request = _build_oauth2_request(request, body)
    status, payload, headers = _server.create_endpoint_response("revocation", oauth2_request)
    return JSONResponse(content=payload or {}, status_code=status, headers=dict(headers))


@router.post("/register")
def register_client(body: dict = Depends(_json_body)):  # noqa: B008
    """Dynamic client registration (RFC 7591).

    Accepts JSON body with optional client_name, redirect_uris, grant_types, scope.
    Returns client_id and client_secret for the registered client.
    """
    client_id = uuid4().hex[:24]
    client_secret = secrets.token_urlsafe(32)

    metadata = {
        "client_name": body.get("client_name", ""),
        "grant_types": body.get("grant_types", ["authorization_code", "refresh_token"]),
        "redirect_uris": body.get("redirect_uris", []),
        "response_types": ["code"],
        "scope": body.get("scope", ""),
        "token_endpoint_auth_method": "client_secret_basic",
    }

    client = OAuth2Client(
        client_id=client_id,
        client_secret=client_secret,
        client_id_issued_at=int(time.time()),
    )
    client.set_client_metadata(metadata)

    session = get_current_session()
    session.add(client)

    return JSONResponse(
        content={
            "client_id": client_id,
            "client_secret": client_secret,
            "client_id_issued_at": client.client_id_issued_at,
            "client_secret_expires_at": 0,
            **client.client_metadata,
        },
        status_code=201,
    )
