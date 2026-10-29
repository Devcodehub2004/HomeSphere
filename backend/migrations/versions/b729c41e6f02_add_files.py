"""Add personal cloud files; preserve the legacy homes table and its rows."""
from alembic import op
import sqlalchemy as sa

revision = "b729c41e6f02"
down_revision = "3715cdabacc9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("storage_key", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_files_size"),
        sa.CheckConstraint("state IN ('uploading', 'ready', 'deleting')", name="ck_files_state"),
    )


def downgrade():
    # Refuse a destructive rollback if files are still recorded.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM files")).scalar_one():
        raise RuntimeError("Refusing to drop nonempty files table; export/delete files first")
    op.drop_table("files")
