"""Single-owner, database-backed cookie sessions for the local HomeSphere demo."""
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth_models import AuthSession, Owner
from app.database import get_db

COOKIE_NAME = "homesphere_session"
SESSION_SECONDS = 8 * 60 * 60
COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "false").lower() in {"true", "1"}
PASSWORDS = PasswordHash.recommended()
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
router = APIRouter(prefix="/auth", tags=["Authentication"])
_attempts = deque()
_attempt_lock = threading.Lock()
_verify_lock = threading.Lock()


def token_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def require_same_origin(request: Request):
    origin = request.headers.get("origin", "")
    try:
        parsed = urlsplit(origin)
    except ValueError:
        raise HTTPException(403, "A same-origin request is required")
    if (parsed.scheme != request.url.scheme or parsed.netloc.lower() != request.url.netloc.lower()
            or parsed.path or parsed.query or parsed.fragment
            or request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}):
        raise HTTPException(403, "A same-origin request is required")


def require_owner(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME, "")
    unauthorized = HTTPException(401, "Please sign in", headers={"Cache-Control": "no-store"})
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise unauthorized
    session = db.get(AuthSession, token_digest(token))
    if session is None:
        raise unauthorized
    expiry = session.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        raise unauthorized
    owner = db.get(Owner, session.owner_id)
    if owner is None:
        raise unauthorized
    return owner


def protect_data_routes(request: Request, db: Session = Depends(get_db)):
    if request.url.path.split("/")[1] in {"files", "homes", "folders"}:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_same_origin(request)
        require_owner(request, db)


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def reserve_login_attempt():
    now = time.monotonic()
    with _attempt_lock:
        while _attempts and _attempts[0] <= now - 60:
            _attempts.popleft()
        if len(_attempts) >= 10:
            raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.",
                                headers={"Retry-After": "60", "Cache-Control": "no-store"})
        _attempts.append(now)


@router.post("/login", dependencies=[Depends(require_same_origin)])
def login(payload: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    reserve_login_attempt()
    if not _verify_lock.acquire(blocking=False):
        raise HTTPException(429, "Another sign-in is in progress. Try again shortly.",
                            headers={"Retry-After": "2"})
    try:
        owner = db.get(Owner, 1)
        username_matches = owner is not None and secrets.compare_digest(
            payload.username.strip().lower().encode(), owner.username.encode())
        try:
            verified = PASSWORDS.verify(payload.password, owner.password_hash if username_matches else DUMMY_HASH)
        except (UnknownHashError, ValueError):
            raise HTTPException(503, "Sign-in is temporarily unavailable")
        if not username_matches or not verified:
            raise HTTPException(401, "Invalid username or password", headers={"Cache-Control": "no-store"})
    finally:
        _verify_lock.release()
    now = datetime.now(timezone.utc)
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    old_token = request.cookies.get(COOKIE_NAME, "")
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", old_token):
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(old_token)))
    # Keep at most ten active sessions, including this new session.
    older = db.scalars(select(AuthSession.token_hash).where(AuthSession.owner_id == owner.id)
                       .order_by(AuthSession.created_at.desc(), AuthSession.token_hash).offset(9)).all()
    if older:
        db.execute(delete(AuthSession).where(AuthSession.token_hash.in_(older)))
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=token_digest(token), owner_id=owner.id,
                       expires_at=now + timedelta(seconds=SESSION_SECONDS)))
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, path="/",
                        httponly=True, secure=COOKIE_SECURE, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return {"username": owner.username}


@router.get("/me")
def me(response: Response, owner: Owner = Depends(require_owner)):
    response.headers["Cache-Control"] = "no-store"
    return {"username": owner.username}


@router.post("/logout", status_code=204, dependencies=[Depends(require_same_origin)])
def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME, "")
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(token)))
        db.commit()
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return response
