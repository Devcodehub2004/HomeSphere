import os
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.cloud_models import Folder


def folder_key(value: str | None) -> str | None:
    if value in {None, "root"}:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        raise HTTPException(422, "Folder must be a UUID or root")


def require_folder(db: Session, folder_id: str | None, owner_id: int):
    if folder_id is None:
        return None
    folder = db.get(Folder, folder_id)
    if folder is None or folder.owner_id != owner_id:
        raise HTTPException(404, "Folder not found")
    return folder


def download_response(store, record):
    """Caller holds the volume lock; an open descriptor survives concurrent deletion."""
    try:
        fd = os.open(store.path(record.storage_key), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise HTTPException(409, "Stored content is missing")
    source = os.fdopen(fd, "rb")

    def chunks():
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()

    return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(record.name, safe=""),
        "Content-Length": str(record.size_bytes),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
    })
