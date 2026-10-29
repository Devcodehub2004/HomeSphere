"""Compact folder, recycle-bin and public-share API, sharing the durable volume lock."""
from datetime import datetime, timedelta, timezone
import re
import secrets
import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_owner, token_digest
from app.auth_models import Owner
from app.cloud_access import download_response, folder_key, require_folder
from app.cloud_models import FileShare, Folder
from app.database import get_db
from app.file_models import StoredFile
from app.file_schemas import FileRead, FileRename
from app.files import operation
from app.storage import FileStore, get_store

router = APIRouter(tags=["Cloud"])


class FolderCreate(FileRename):
    parent_id: UUID | None = None


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    parent_id: str | None
    name: str
    created_at: datetime


@router.post("/folders", response_model=FolderRead, status_code=201)
def create_folder(payload: FolderCreate, db: Session = Depends(get_db),
                  store: FileStore = Depends(get_store), owner: Owner = Depends(require_owner)):
    with operation(db, store):
        parent = str(payload.parent_id) if payload.parent_id else None
        require_folder(db, parent, owner.id)
        folder = Folder(id=str(uuid4()), owner_id=owner.id, parent_id=parent, name=payload.name)
        db.add(folder)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "A folder with that name already exists here")
        return FolderRead.model_validate(folder)


@router.get("/folders", response_model=list[FolderRead])
def list_folders(parent_id: str = "root", skip: int = Query(0, ge=0),
                 limit: int = Query(100, ge=1, le=100), db: Session = Depends(get_db),
                 owner: Owner = Depends(require_owner)):
    parent = folder_key(parent_id)
    require_folder(db, parent, owner.id)
    return db.scalars(select(Folder).where(Folder.owner_id == owner.id, Folder.parent_id == parent)
                      .order_by(Folder.name, Folder.id).offset(skip).limit(limit)).all()


@router.get("/files/recent", response_model=list[FileRead])
def recent_files(limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db),
                 store: FileStore = Depends(get_store), owner: Owner = Depends(require_owner)):
    with operation(db, store):
        records = db.scalars(select(StoredFile).where(StoredFile.owner_id == owner.id,
            StoredFile.state == "ready", StoredFile.deleted_at.is_(None))
            .order_by(StoredFile.created_at.desc(), StoredFile.id).limit(limit)).all()
        return [FileRead.model_validate(record) for record in records]


@router.post("/files/{file_id}/restore", response_model=FileRead)
def restore_file(file_id: UUID, db: Session = Depends(get_db), store: FileStore = Depends(get_store),
                 owner: Owner = Depends(require_owner)):
    with operation(db, store):
        record = store.ready(db, str(file_id), owner.id, trashed=True)
        require_folder(db, record.folder_id, owner.id)
        # Check content before making it visible again; never discard missing metadata.
        try:
            fd = os.open(store.path(record.storage_key), os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            raise HTTPException(409, "Stored content is missing")
        os.close(fd)
        record.deleted_at = None
        db.commit()
        return FileRead.model_validate(record)


@router.delete("/files/{file_id}/permanent", status_code=204)
def permanently_delete(file_id: UUID, db: Session = Depends(get_db), store: FileStore = Depends(get_store),
                        owner: Owner = Depends(require_owner)):
    with operation(db, store):
        store.delete(db, store.ready(db, str(file_id), owner.id, trashed=True))


class ShareCreate(BaseModel):
    expires_in_hours: int = Field(default=24, ge=1, le=168)


class ShareRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


@router.post("/files/{file_id}/shares", status_code=201)
def create_share(file_id: UUID, payload: ShareCreate, response: Response,
                  db: Session = Depends(get_db), store: FileStore = Depends(get_store),
                  owner: Owner = Depends(require_owner)):
    with operation(db, store):
        record = store.ready(db, str(file_id), owner.id)
        token = secrets.token_urlsafe(32)
        share = FileShare(id=str(uuid4()), file_id=record.id, token_hash=token_digest(token),
                          expires_at=datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours))
        db.add(share)
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {**ShareRead.model_validate(share).model_dump(), "path": f"/public/{token}"}


@router.get("/files/{file_id}/shares", response_model=list[ShareRead])
def list_shares(file_id: UUID, response: Response, db: Session = Depends(get_db),
                 store: FileStore = Depends(get_store), owner: Owner = Depends(require_owner)):
    with operation(db, store):
        record = store.ready(db, str(file_id), owner.id)
        response.headers["Cache-Control"] = "no-store"
        return db.scalars(select(FileShare).where(FileShare.file_id == record.id)
                          .order_by(FileShare.created_at.desc())).all()


@router.delete("/files/{file_id}/shares/{share_id}", status_code=204)
def revoke_share(file_id: UUID, share_id: UUID, db: Session = Depends(get_db),
                   store: FileStore = Depends(get_store), owner: Owner = Depends(require_owner)):
    with operation(db, store):
        record = store.ready(db, str(file_id), owner.id)
        share = db.get(FileShare, str(share_id))
        if share is None or share.file_id != record.id:
            raise HTTPException(404, "Share not found")
        share.revoked_at = share.revoked_at or datetime.now(timezone.utc)
        db.commit()


@router.get("/public/{token}")
def public_download(token: str, db: Session = Depends(get_db), store: FileStore = Depends(get_store)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(404, "Link unavailable")
    with operation(db, store):
        now = datetime.now(timezone.utc)
        record = db.scalar(select(StoredFile).join(FileShare, FileShare.file_id == StoredFile.id)
            .join(Owner, Owner.id == StoredFile.owner_id)
            .where(FileShare.token_hash == token_digest(token), FileShare.revoked_at.is_(None),
                   FileShare.expires_at > now, StoredFile.state == "ready", StoredFile.deleted_at.is_(None)))
        if record is None:
            raise HTTPException(404, "Link unavailable", headers={"Cache-Control": "no-store"})
        return download_response(store, record)
