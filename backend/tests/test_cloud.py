from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.auth import require_owner, token_digest
from app.cloud_models import FileShare
from app.file_models import StoredFile
from app.main import app


def upload(client, name="notes.txt", folder=None):
    return client.post('/files', params={"folder_id": folder} if folder else {},
                       files={"file": (name, b"hello", "text/plain")})


def folder(client, name="Projects", parent=None):
    return client.post('/folders', json={"name": name, "parent_id": parent})


def share(client, file_id, hours=24):
    response = client.post(f'/files/{file_id}/shares', json={"expires_in_hours": hours})
    assert response.status_code == 201, response.text
    return response.json()


def test_nested_folder_browsing_and_search(client):
    root = folder(client).json()['id']
    child = folder(client, 'Design', root).json()['id']
    top = upload(client, 'root.txt').json()['id']
    nested = upload(client, 'Report_100%.txt', child).json()['id']
    assert [x['id'] for x in client.get('/folders').json()] == [root]
    assert [x['id'] for x in client.get('/folders', params={'parent_id': root}).json()] == [child]
    assert [x['id'] for x in client.get('/files?folder_id=root').json()] == [top]
    assert [x['id'] for x in client.get('/files', params={'folder_id': child}).json()] == [nested]
    assert [x['id'] for x in client.get('/files', params={'q': 'REPORT_100%'}).json()] == [nested]
    assert client.get('/files', params={'q': '100_'}).json() == []
    assert len(client.get('/files').json()) == 2
    assert folder(client, 'projects').status_code == 409
    assert folder(client, 'Design', root).status_code == 409
    assert folder(client, 'Design').status_code == 201
    assert client.get('/folders?limit=101').status_code == 422


@pytest.mark.parametrize('name', ['../escape', 'a/b', 'a\\b', '.', '..', '.hidden', 'CON', 'a\x00b'])
def test_unsafe_folder_names(client, name):
    assert folder(client, name).status_code == 422
    assert client.get('/folders').json() == []


def test_invalid_and_missing_parent(client):
    missing = str(uuid4())
    assert folder(client, parent=missing).status_code == 404
    assert upload(client, folder=missing).status_code == 404
    assert client.get('/files', params={'folder_id': missing}).status_code == 404
    assert client.get('/folders', params={'parent_id': missing}).status_code == 404
    assert upload(client, folder='../bad').status_code == 422
    assert client.get('/folders?parent_id=../bad').status_code == 422
    assert client.get('/files').json() == []


def test_recent_is_global_stable_and_excludes_trash(client, file_env):
    parent = folder(client).json()['id']
    first = upload(client, 'old.txt').json()['id']
    second = upload(client, 'new.txt', parent).json()['id']
    with file_env[0]() as db:
        db.get(StoredFile, first).created_at = datetime.now(timezone.utc) - timedelta(days=2)
        db.commit()
    assert [x['id'] for x in client.get('/files/recent?limit=1').json()] == [second]
    assert client.delete(f'/files/{second}').status_code == 204
    assert [x['id'] for x in client.get('/files/recent').json()] == [first]
    assert client.get('/files/recent?limit=0').status_code == 422


def test_recycle_restore_purge_preserves_original_folder_and_bytes(client, file_env):
    parent = folder(client).json()['id']
    record = upload(client, folder=parent).json()
    file_id = record['id']
    with file_env[0]() as db:
        key = db.get(StoredFile, file_id).storage_key
    assert client.delete(f'/files/{file_id}/permanent').status_code == 404
    assert client.delete(f'/files/{file_id}').status_code == 204
    assert file_env[1].path(key).read_bytes() == b'hello'
    assert client.get('/files').json() == []
    assert client.get('/files?trashed=true').json()[0]['deleted_at']
    assert client.get(f'/files/{file_id}/download').status_code == 404
    assert client.patch(f'/files/{file_id}', json={'name': 'x'}).status_code == 404
    assert client.post(f'/files/{file_id}/shares', json={}).status_code == 404
    restored = client.post(f'/files/{file_id}/restore')
    assert restored.status_code == 200
    assert restored.json()['folder_id'] == parent
    assert restored.json()['sha256'] == record['sha256']
    assert restored.json()['deleted_at'] is None
    assert client.get(f'/files/{file_id}/download').content == b'hello'
    assert client.post(f'/files/{file_id}/restore').status_code == 404
    assert client.delete(f'/files/{file_id}').status_code == 204
    assert client.delete(f'/files/{file_id}/permanent').status_code == 204
    assert client.get('/files?trashed=true').json() == []
    assert not file_env[1].path(key).exists()


def test_missing_payload_restore_stays_in_bin(client, file_env):
    file_id = upload(client).json()['id']
    assert client.delete(f'/files/{file_id}').status_code == 204
    with file_env[0]() as db:
        file_env[1].path(db.get(StoredFile, file_id).storage_key).unlink()
    assert client.post(f'/files/{file_id}/restore').status_code == 409
    assert len(client.get('/files?trashed=true').json()) == 1


def test_links_are_random_hashed_expire_and_revoke(client, anonymous, file_env):
    file_id = upload(client).json()['id']
    first = share(client, file_id)
    second = share(client, file_id, 1)
    assert first['path'] != second['path']
    token = first['path'].rsplit('/', 1)[1]
    assert len(token) == 43
    assert client.get(f'/files/{file_id}/shares').status_code == 200
    assert token not in client.get(f'/files/{file_id}/shares').text
    with file_env[0]() as db:
        row = db.get(FileShare, first['id'])
        assert row.token_hash == token_digest(token)
        assert token not in str(row.__dict__)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert anonymous.get(first['path']).status_code == 404
    download = anonymous.get(second['path'])
    assert download.status_code == 200 and download.content == b'hello'
    assert download.headers['cache-control'] == 'no-store'
    assert download.headers['content-disposition'].startswith('attachment;')
    assert client.delete(f'/files/{file_id}/shares/{second["id"]}').status_code == 204
    assert anonymous.get(second['path']).status_code == 404
    assert anonymous.get('/public/' + 'x' * 43).status_code == 404
    assert anonymous.get('/public/short').status_code == 404
    assert client.post(f'/files/{file_id}/shares', json={'expires_in_hours': 169}).status_code == 422


def test_trash_revokes_links_permanently_and_purge_removes_share_rows(client, anonymous, file_env):
    file_id = upload(client).json()['id']
    link = share(client, file_id)
    assert anonymous.get(link['path']).status_code == 200
    assert client.delete(f'/files/{file_id}').status_code == 204
    assert anonymous.get(link['path']).status_code == 404
    assert client.post(f'/files/{file_id}/restore').status_code == 200
    assert anonymous.get(link['path']).status_code == 404
    assert client.delete(f'/files/{file_id}').status_code == 204
    assert client.delete(f'/files/{file_id}/permanent').status_code == 204
    with file_env[0]() as db:
        assert db.scalar(select(FileShare)) is None


def test_private_routes_require_session_and_same_origin(client, anonymous):
    file_id = upload(client).json()['id']
    for path in ['/folders', '/files/recent', '/files?trashed=true', f'/files/{file_id}/shares']:
        assert anonymous.get(path).status_code == 401
    for method, path, payload in [('post', '/folders', {'name': 'test'}),
        ('post', f'/files/{file_id}/restore', None), ('delete', f'/files/{file_id}/permanent', None),
        ('post', f'/files/{file_id}/shares', {}), ('delete', f'/files/{file_id}/shares/{uuid4()}', None)]:
        assert getattr(anonymous, method)(path, **({'json': payload} if payload is not None else {})).status_code == 401
        assert getattr(client, method)(path, headers={'Origin': 'https://evil.example'},
            **({'json': payload} if payload is not None else {})).status_code == 403


def test_resource_ownership_is_checked_even_with_authenticated_identity(client):
    # The product has one owner. Substitute another authenticated identity to prove
    # resource checks do not merely rely on being logged in.
    parent = folder(client).json()['id']
    file_id = upload(client, folder=parent).json()['id']
    link = share(client, file_id)
    app.dependency_overrides[require_owner] = lambda: SimpleNamespace(id=2)
    try:
        assert client.get('/files').json() == []
        assert client.get('/files/recent').json() == []
        assert client.get('/folders').json() == []
        assert folder(client, parent=parent).status_code == 404
        assert upload(client, folder=parent).status_code == 404
        assert client.get(f'/files/{file_id}/download').status_code == 404
        assert client.delete(f'/files/{file_id}').status_code == 404
        assert client.patch(f'/files/{file_id}', json={'name': 'x'}).status_code == 404
        assert client.post(f'/files/{file_id}/shares', json={}).status_code == 404
        assert client.get(f'/files/{file_id}/shares').status_code == 404
        assert client.delete(f'/files/{file_id}/shares/{link["id"]}').status_code == 404
    finally:
        app.dependency_overrides.pop(require_owner)
    client.delete(f'/files/{file_id}')
    app.dependency_overrides[require_owner] = lambda: SimpleNamespace(id=2)
    try:
        assert client.get('/files?trashed=true').json() == []
        assert client.post(f'/files/{file_id}/restore').status_code == 404
        assert client.delete(f'/files/{file_id}/permanent').status_code == 404
    finally:
        app.dependency_overrides.pop(require_owner)


def test_soft_delete_failed_commit_keeps_file_and_share_active(client, anonymous, monkeypatch):
    file_id = upload(client).json()['id']
    link = share(client, file_id)
    from sqlalchemy.orm import Session
    commit = Session.commit
    def fail(self):
        raise SQLAlchemyError('failed soft delete')
    monkeypatch.setattr(Session, 'commit', fail)
    assert client.delete(f'/files/{file_id}').status_code == 503
    monkeypatch.setattr(Session, 'commit', commit)
    assert client.get(f'/files/{file_id}/download').content == b'hello'
    assert anonymous.get(link['path']).status_code == 200
