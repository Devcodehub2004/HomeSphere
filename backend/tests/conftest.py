from pathlib import Path
from datetime import datetime, timedelta, timezone
import secrets
import os

from app.auth import COOKIE_NAME, PASSWORDS, token_digest
from app.auth_models import Owner, AuthSession
import app.auth as auth_api

TEST_TOKEN = secrets.token_urlsafe(32)
TEST_PASSWORD = "test-owner-password-2026"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.storage import FileStore, get_store
import app.files as files_api


@pytest.fixture(scope="session")
def owner_hash():
    return PASSWORDS.hash(TEST_PASSWORD)


@pytest.fixture
def file_env(tmp_path, monkeypatch, owner_hash):
    test_url = os.getenv("HOMESPHERE_TEST_DATABASE_URL")
    if test_url:
        from sqlalchemy.engine import make_url
        parsed = make_url(test_url)
        if not (parsed.database or "").startswith("homesphere_test_"):
            raise RuntimeError("PostgreSQL tests require a disposable homesphere_test_* database")
        engine = create_engine(test_url)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine(
            "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    auth_api._attempts.clear()
    with sessions() as db:
        db.add(Owner(id=1, username="demo", password_hash=owner_hash))
        db.flush()
        db.add(AuthSession(token_hash=token_digest(TEST_TOKEN), owner_id=1,
                           expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.commit()
    store = FileStore(tmp_path / "uploads", max_size=1024)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_store] = lambda: store
    monkeypatch.setattr(files_api, "SessionLocal", sessions)
    monkeypatch.setattr(files_api, "get_store", lambda: store)
    try:
        yield sessions, store
    finally:
        app.dependency_overrides.clear()
        if test_url:
            Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(file_env):
    with TestClient(app, headers={"Origin": "http://testserver"},
                    cookies={COOKIE_NAME: TEST_TOKEN}) as test_client:
        yield test_client


@pytest.fixture
def anonymous(file_env):
    with TestClient(app, headers={"Origin": "http://testserver"}) as test_client:
        yield test_client
