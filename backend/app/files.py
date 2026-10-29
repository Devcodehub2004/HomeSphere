import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.file_models import StoredFile
from app.file_schemas import FileRead, FileRename
from app.storage import FileStore, get_store
from app.auth import require_owner
from app.auth_models import Owner
from app.cloud_models import FileShare
from app.cloud_access import download_response, folder_key, require_folder

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["Files"])


@asynccontextmanager
async def lifespan(app):
    store = get_store()
    with store.locked(), SessionLocal() as db:
        store.recover(db)
    yield


def local_write(request: Request):
    # Browser cross-origin forms must not mutate an unauthenticated localhost demo.
    if request.method in {"POST", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.url.netloc:
            raise HTTPException(403, "Cross-origin writes are disabled")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Cross-site writes are disabled")


router.dependencies.append(Depends(local_write))


@contextmanager
def operation(db: Session, store: FileStore):
    with store.locked():
        try:
            store.recover(db)
            yield
        except HTTPException:
            db.rollback()
            store.recover(db)
            raise
        except (OSError, SQLAlchemyError):
            db.rollback()
            # Do not guess whether a failed DB commit took effect. Recovery reads its journal.
            try:
                store.recover(db)
            except (OSError, SQLAlchemyError):
                db.rollback()
                logger.exception("File operation recovery deferred until next request/startup")
            logger.exception("File operation failed")
            raise HTTPException(503, "Storage temporarily unavailable; retry the request")


@router.post("", response_model=FileRead, status_code=201)
def upload_file(
    file: UploadFile = File(...), db: Session = Depends(get_db),
    store: FileStore = Depends(get_store),
    folder_id: str | None = Query(None), owner: Owner = Depends(require_owner),
):
    with operation(db, store):
        target = folder_key(folder_id)
        require_folder(db, target, owner.id)
        return FileRead.model_validate(store.upload(db, file, owner.id, target))


@router.get("", response_model=list[FileRead])
def list_files(
    skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), store: FileStore = Depends(get_store),
    owner: Owner = Depends(require_owner), folder_id: str | None = Query(None),
    trashed: bool = False, q: str = Query("", max_length=255),
):
    with operation(db, store):
        statement = select(StoredFile).where(StoredFile.state == "ready", StoredFile.owner_id == owner.id,
            StoredFile.deleted_at.is_not(None) if trashed else StoredFile.deleted_at.is_(None))
        if folder_id is not None:
            target = folder_key(folder_id)
            require_folder(db, target, owner.id)
            statement = statement.where(StoredFile.folder_id == target)
        if q:
            statement = statement.where(StoredFile.name.icontains(q, autoescape=True))
        records = db.scalars(
            statement
            .order_by(StoredFile.created_at.desc(), StoredFile.id).offset(skip).limit(limit)
        ).all()
        return [FileRead.model_validate(record) for record in records]


@router.get("/{file_id}/download")
def download_file(
    file_id: UUID, db: Session = Depends(get_db), store: FileStore = Depends(get_store),
    owner: Owner = Depends(require_owner),
):
    with operation(db, store):
        return download_response(store, store.ready(db, str(file_id), owner.id))


@router.patch("/{file_id}", response_model=FileRead)
def rename_file(
    file_id: UUID, payload: FileRename, db: Session = Depends(get_db),
    store: FileStore = Depends(get_store),
    owner: Owner = Depends(require_owner),
):
    with operation(db, store):
        record = store.ready(db, str(file_id), owner.id)
        record.name = payload.name
        db.commit()
        return FileRead.model_validate(record)


@router.delete("/{file_id}", status_code=204)
def delete_file(
    file_id: UUID, db: Session = Depends(get_db), store: FileStore = Depends(get_store),
    owner: Owner = Depends(require_owner),
):
    with operation(db, store):
        record = store.ready(db, str(file_id), owner.id)
        record.deleted_at = datetime.now(timezone.utc)
        # Restoring a file must never silently reactivate an old shared link.
        db.execute(update(FileShare).where(FileShare.file_id == record.id,
            FileShare.revoked_at.is_(None)).values(revoked_at=record.deleted_at))
        db.commit()
