from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Home(Base):
    __tablename__ = "homes"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    city: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

# Register personal cloud metadata for Alembic, retaining the legacy Home model.
from app.file_models import StoredFile  # noqa: E402,F401
from app.auth_models import Owner, AuthSession  # noqa: E402,F401
from app.cloud_models import Folder, FileShare  # noqa: E402,F401
