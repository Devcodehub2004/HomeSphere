"""Small, journaled local file store; Linux flock serializes workers sharing a volume."""
import fcntl
import hashlib
import os
import re
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.file_models import StoredFile
from app.cloud_models import FileShare
from app.file_schemas import safe_filename

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_BYTES", str(25 * 1024 * 1024)))
if MAX_FILE_SIZE <= 0:
    raise ValueError("MAX_FILE_SIZE_BYTES must be positive")


class FileStore:
    def __init__(self, root: Path, max_size: int = MAX_FILE_SIZE):
        self.root = root.resolve()
        self.max_size = max_size
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def locked(self):
        fd = os.open(self.root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def path(self, key: str, partial: bool = False) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", key):
            raise OSError("Invalid internal storage identifier")
        return self.root / (key + (".part" if partial else ""))

    def sync_directory(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def recover(self, db: Session):
        """Caller holds the lock. Finish durable delete intents and discard interrupted uploads."""
        pending = db.scalars(select(StoredFile).where(StoredFile.state != "ready")).all()
        for record in pending:
            self.path(record.storage_key, partial=True).unlink(missing_ok=True)
            self.path(record.storage_key).unlink(missing_ok=True)
            self.sync_directory()
            db.execute(delete(FileShare).where(FileShare.file_id == record.id))
            db.delete(record)
        if pending:
            db.commit()

    def ready(self, db: Session, file_id: str, owner_id: int = 1, *, trashed: bool = False) -> StoredFile:
        record = db.get(StoredFile, file_id)
        if (record is None or record.state != "ready" or record.owner_id != owner_id
                or (record.deleted_at is not None) != trashed):
            raise HTTPException(404, "File not found")
        return record

    def upload(self, db: Session, upload: UploadFile, owner_id: int = 1, folder_id: str | None = None) -> StoredFile:
        try:
            name = safe_filename(upload.filename or "")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        content_type = upload.content_type or "application/octet-stream"
        if len(content_type) > 255 or not re.fullmatch(r"[\w.+-]+/[\w.+-]+", content_type, re.ASCII):
            content_type = "application/octet-stream"
        record = StoredFile(
            id=str(uuid4()), storage_key=uuid4().hex, name=name,
            size_bytes=0, content_type=content_type, sha256="", state="uploading",
            owner_id=owner_id, folder_id=folder_id,
        )
        db.add(record)
        # Persist intent before any payload is created, so restart recovery is deterministic.
        db.commit()
        digest = hashlib.sha256()
        size = 0
        with self.path(record.storage_key, partial=True).open("xb") as destination:
            os.chmod(destination.name, 0o600)
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > self.max_size:
                    raise HTTPException(413, f"File exceeds {self.max_size} bytes")
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(self.path(record.storage_key, partial=True), self.path(record.storage_key))
        self.sync_directory()
        record.size_bytes = size
        record.sha256 = digest.hexdigest()
        record.state = "ready"
        db.commit()
        return record

    def delete(self, db: Session, record: StoredFile):
        record.state = "deleting"
        db.commit()
        # If removal fails, the journal keeps this hidden and recovery retries safely.
        self.path(record.storage_key).unlink(missing_ok=True)
        self.sync_directory()
        db.execute(delete(FileShare).where(FileShare.file_id == record.id))
        db.delete(record)
        db.commit()


@lru_cache
def get_store() -> FileStore:
    return FileStore(Path(os.getenv("UPLOAD_DIR", "/data/uploads")))
