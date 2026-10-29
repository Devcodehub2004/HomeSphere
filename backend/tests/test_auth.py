from datetime import datetime, timedelta, timezone
import secrets
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.auth import COOKIE_NAME, SESSION_SECONDS, token_digest
from app.auth_models import AuthSession, Owner

PASSWORD = 'test-owner-password-2026'


def sign_in(client, **changes):
    return client.post('/auth/login', json={'username': 'demo', 'password': PASSWORD, **changes})


@pytest.mark.parametrize('method,path,options', [
    ('get', '/files', {}),
    ('post', '/files', {'files': {'file': ('private.txt', b'secret')}}),
    ('get', f'/files/{uuid4()}/download', {}),
    ('patch', f'/files/{uuid4()}', {'json': {'name': 'renamed.txt'}}),
    ('delete', f'/files/{uuid4()}', {}),
    ('get', '/auth/me', {}),
])
def test_anonymous_data_access_is_denied(anonymous, method, path, options):
    assert getattr(anonymous, method)(path, **options).status_code == 401


def test_health_and_schema_stay_public(anonymous):
    health = anonymous.get('/health')
    assert health.status_code == 200
    assert health.json()['status'] == 'healthy'
    for path in ('/db-health', '/openapi.json', '/docs'):
        assert anonymous.get(path).status_code == 200


def test_login_cookie_hash_and_logout_revocation(anonymous, file_env):
    response = sign_in(anonymous)
    assert response.status_code == 200
    assert response.json() == {'username': 'demo'}
    assert response.headers['cache-control'] == 'no-store'
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'path=/' in cookie
    assert f'max-age={SESSION_SECONDS}' in cookie
    token = anonymous.cookies[COOKIE_NAME]
    assert len(token) == 43
    with file_env[0]() as db:
        assert db.get(AuthSession, token) is None
        assert db.get(AuthSession, token_digest(token)) is not None
    assert anonymous.get('/auth/me').json() == {'username': 'demo'}
    assert anonymous.get('/files').status_code == 200
    assert anonymous.post('/auth/logout').status_code == 204
    anonymous.cookies.clear()
    anonymous.cookies.set(COOKIE_NAME, token)
    assert anonymous.get('/files').status_code == 401
    with file_env[0]() as db:
        assert db.get(AuthSession, token_digest(token)) is None


def test_invalid_credentials_do_not_create_sessions(anonymous, file_env):
    with file_env[0]() as db:
        before = db.scalar(select(func.count()).select_from(AuthSession))
    wrong_password = sign_in(anonymous, password='wrong-password')
    wrong_username = sign_in(anonymous, username='unknown')
    assert wrong_password.status_code == wrong_username.status_code == 401
    assert wrong_password.json() == wrong_username.json()
    assert COOKIE_NAME not in anonymous.cookies
    with file_env[0]() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == before


def test_login_rotates_the_current_session(anonymous, file_env):
    assert sign_in(anonymous).status_code == 200
    first = anonymous.cookies[COOKIE_NAME]
    assert sign_in(anonymous).status_code == 200
    second = anonymous.cookies[COOKIE_NAME]
    assert first != second
    with file_env[0]() as db:
        assert db.get(AuthSession, token_digest(first)) is None
        assert db.get(AuthSession, token_digest(second)) is not None


def test_expired_and_malformed_sessions_are_denied(anonymous, file_env):
    token = secrets.token_urlsafe(32)
    with file_env[0]() as db:
        db.add(AuthSession(token_hash=token_digest(token), owner_id=1,
                           expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()
    for value in (token, 'tampered-cookie', secrets.token_urlsafe(32)):
        anonymous.cookies.clear()
        anonymous.cookies.set(COOKIE_NAME, value)
        assert anonymous.get('/files').status_code == 401


@pytest.mark.parametrize('origin', [None, 'null', 'https://evil.example',
                                   'http://testserver:1234', 'https://testserver'])
def test_login_requires_exact_origin(anonymous, origin):
    anonymous.headers.pop('origin', None)
    headers = {} if origin is None else {'Origin': origin}
    assert anonymous.post('/auth/login', json={'username': 'demo', 'password': PASSWORD},
                          headers=headers).status_code == 403


def test_cross_site_logout_cannot_revoke_a_session(client):
    assert client.post('/auth/logout', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/files').status_code == 200
    assert client.post('/auth/logout', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.get('/files').status_code == 200


def test_missing_origin_blocks_cookie_authenticated_writes(client):
    client.headers.pop('origin', None)
    assert client.post('/files', files={'file': ('a.txt', b'a')}).status_code == 403
    assert client.post('/auth/logout').status_code == 403
    assert client.get('/files').status_code == 200


def test_login_throttling(anonymous):
    for _ in range(10):
        assert sign_in(anonymous, password='wrong-password').status_code == 401
    response = sign_in(anonymous)
    assert response.status_code == 429
    assert response.headers['retry-after'] == '60'


def test_logout_is_idempotent(anonymous):
    assert anonymous.post('/auth/logout').status_code == 204
    assert anonymous.post('/auth/logout').status_code == 204


def test_one_owner_constraint(file_env):
    from sqlalchemy.exc import IntegrityError
    with file_env[0]() as db:
        db.add(Owner(id=2, username='second', password_hash='not-used'))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_download_requires_the_cookie_even_with_known_file_id(client, anonymous):
    created = client.post('/files', files={'file': ('private.txt', b'private')}).json()
    path = '/files/' + created['id'] + '/download'
    assert anonymous.get(path).status_code == 401
    assert client.get(path).content == b'private'


def test_session_count_is_bounded(anonymous, file_env):
    with file_env[0]() as db:
        for _ in range(15):
            db.add(AuthSession(token_hash=token_digest(secrets.token_urlsafe(32)), owner_id=1,
                               expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.commit()
    assert sign_in(anonymous).status_code == 200
    with file_env[0]() as db:
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 10
