import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.file_models import StoredFile
from app.main import app
from app.storage import FileStore


def upload(client, name="notes.txt", data=b"hello"):
    return client.post("/files", files={"file": (name, data, "text/plain")})


def test_full_lifecycle(client, file_env):
    sessions, store = file_env
    created = upload(client)
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["name"] == "notes.txt"
    assert record["size_bytes"] == 5
    assert record["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert "storage_key" not in record
    file_id = record["id"]
    with sessions() as db:
        key = db.get(StoredFile, file_id).storage_key
    assert store.path(key).read_bytes() == b"hello"
    assert store.path(key).name != "notes.txt"
    assert client.get("/files").json() == [record]
    result = client.get(f"/files/{file_id}/download")
    assert result.content == b"hello"
    assert result.headers["content-type"] == "application/octet-stream"
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["content-disposition"].startswith("attachment;")
    renamed = client.patch(f"/files/{file_id}", json={"name": "résumé.txt"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "résumé.txt"
    assert store.path(key).read_bytes() == b"hello"
    result = client.get(f"/files/{file_id}/download")
    assert "r%C3%A9sum%C3%A9.txt" in result.headers["content-disposition"]
    assert client.delete(f"/files/{file_id}").status_code == 204
    assert store.path(key).exists()  # DELETE is now reversible; permanent deletion is explicit.
    assert client.get('/files?trashed=true').json()[0]['id'] == file_id
    assert client.delete(f'/files/{file_id}/permanent').status_code == 204
    assert not store.path(key).exists()
    assert client.get("/files").json() == []
    assert client.get(f"/files/{file_id}/download").status_code == 404
    assert client.delete(f"/files/{file_id}").status_code == 404


@pytest.mark.parametrize("name", [
    "../escape.txt", "dir/file.txt", "dir\\file.txt", ".", "..", ".hidden",
    "a\r\nb.txt", "a\x00.txt", "CON.txt", "a:b.txt", "a" * 256, "é" * 128,
])
def test_unsafe_names(client, file_env, name):
    # Some HTTP libraries reject controls before sending, so use schema for those too.
    from app.file_schemas import safe_filename
    with pytest.raises(ValueError):
        safe_filename(name)
    if "\x00" not in name and "\r" not in name:
        assert upload(client, name).status_code == 422
    assert client.get("/files").json() == []


def test_rename_validation_and_missing_ids(client):
    file_id = upload(client).json()["id"]
    assert client.patch(f"/files/{file_id}", json={"name": "../bad"}).status_code == 422
    assert client.patch(f"/files/{file_id}", json={"name": "   "}).status_code == 422
    assert client.get("/files/not-a-uuid/download").status_code == 422
    missing = str(uuid4())
    assert client.get(f"/files/{missing}/download").status_code == 404
    assert client.patch(f"/files/{missing}", json={"name": "ok"}).status_code == 404
    assert client.delete(f"/files/{missing}").status_code == 404


def test_exact_limit_empty_and_duplicate_names(client, file_env):
    first = upload(client, data=b"x" * 1024)
    second = upload(client, data=b"")
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert second.json()["size_bytes"] == 0
    assert len(client.get("/files").json()) == 2
    assert len(client.get("/files?skip=1&limit=1").json()) == 1
    assert client.get("/files?limit=101").status_code == 422


def test_over_limit_cleans_disk_and_database(client, file_env):
    sessions, store = file_env
    assert upload(client, data=b"x" * 1025).status_code == 413
    assert client.get("/files").json() == []
    assert list(store.root.iterdir()) == [store.root / ".lock"]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(StoredFile)) == 0


def test_raw_body_limit_including_without_content_length(client):
    # Larger than the 25 MiB file cap plus multipart overhead, stopped before parsing.
    from app.storage import MAX_FILE_SIZE
    headers = {"content-type": "multipart/form-data; boundary=demo"}
    assert client.post("/files", content=b"x" * (MAX_FILE_SIZE + 65537), headers=headers).status_code == 413
    def chunks():
        for _ in range((MAX_FILE_SIZE + 65536) // 65536 + 2):
            yield b"x" * 65536
    assert client.post("/files", content=chunks(), headers=headers).status_code == 413


def test_storage_write_failure(client, file_env, monkeypatch):
    store = file_env[1]
    def fail_sync():
        raise OSError("disk unavailable")
    monkeypatch.setattr(store, "sync_directory", fail_sync)
    assert upload(client).status_code == 503
    monkeypatch.undo()
    assert client.get("/files").json() == []
    assert list(store.root.iterdir()) == [store.root / ".lock"]


def test_database_commit_failure_preserves_consistency(client, file_env, monkeypatch):
    sessions, store = file_env
    from sqlalchemy.orm import Session
    original = Session.commit
    calls = 0
    def fail_ready_commit(self):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("simulated metadata commit failure")
        return original(self)
    monkeypatch.setattr(Session, "commit", fail_ready_commit)
    assert upload(client).status_code == 503
    assert client.get("/files").json() == []
    assert list(store.root.iterdir()) == [store.root / ".lock"]


def test_delete_failure_is_recovered(client, file_env, monkeypatch):
    record = upload(client).json()
    store = file_env[1]
    original = store.path
    class Unremovable:
        def unlink(self, **kwargs):
            raise PermissionError("simulated disk failure")
    assert client.delete(f"/files/{record['id']}").status_code == 204
    monkeypatch.setattr(store, "path", lambda *a, **kw: Unremovable())
    assert client.delete(f"/files/{record['id']}/permanent").status_code == 503
    monkeypatch.setattr(store, "path", original)
    assert client.get("/files").json() == []
    assert list(store.root.iterdir()) == [store.root / ".lock"]


def test_restart_recovers_journaled_operations_and_keeps_ready(file_env, client):
    sessions, store = file_env
    with sessions() as db, store.locked():
        ready = store.upload(db, UploadFile(filename="keep.txt", file=BytesIO(b"keep")))
        ready_id = ready.id
        for state in ("uploading", "deleting"):
            key = uuid4().hex
            db.add(StoredFile(
                id=str(uuid4()), storage_key=key, name="interrupted.txt",
                size_bytes=4, content_type="text/plain", sha256="", state=state,
            ))
            db.commit()
            store.path(key).write_bytes(b"data")
            store.path(key, partial=True).write_bytes(b"part")
    with TestClient(app, cookies=dict(client.cookies)) as restarted:
        assert [f["id"] for f in restarted.get("/files").json()] == [ready_id]
        assert restarted.get(f"/files/{ready_id}/download").content == b"keep"
    assert len(list(store.root.iterdir())) == 2


def test_missing_payload_retains_metadata(client, file_env):
    sessions, store = file_env
    record = upload(client).json()
    with sessions() as db:
        store.path(db.get(StoredFile, record["id"]).storage_key).unlink()
    assert client.get(f"/files/{record['id']}/download").status_code == 409
    assert len(client.get("/files").json()) == 1
    assert client.delete(f"/files/{record['id']}").status_code == 204


def test_no_path_or_symlink_download(client, file_env, tmp_path):
    sessions, store = file_env
    record = upload(client).json()
    secret = tmp_path / "outside"
    secret.write_bytes(b"secret")
    with sessions() as db:
        path = store.path(db.get(StoredFile, record["id"]).storage_key)
    path.unlink()
    path.symlink_to(secret)
    assert client.get(f"/files/{record['id']}/download").status_code == 503
    assert client.delete(f"/files/{record['id']}").status_code == 204
    assert secret.read_bytes() == b"secret"
    with pytest.raises(OSError):
        store.path("../outside")


def test_cross_origin_and_host_protection(client):
    assert client.post(
        "/files", files={"file": ("a.txt", b"x")}, headers={"Origin": "https://evil.example"},
    ).status_code == 403
    assert client.post(
        "/files", files={"file": ("a.txt", b"x")}, headers={"Sec-Fetch-Site": "cross-site"},
    ).status_code == 403
    assert client.get("/files", headers={"Host": "evil.example"}).status_code == 400
    assert client.post(
        "/files", files={"file": ("a.txt", b"x")}, headers={"Origin": "http://testserver"},
    ).status_code == 201
