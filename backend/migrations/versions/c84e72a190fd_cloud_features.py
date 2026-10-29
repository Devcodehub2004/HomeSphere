"""Add virtual folders, ownership, recycle bin and expiring shares without moving bytes.

Revision ID: c84e72a190fd
Revises: 96963c861318
"""
from alembic import op
import sqlalchemy as sa

revision = "c84e72a190fd"
down_revision = "96963c861318"
branch_labels = None
depends_on = None


def upgrade():
    # Existing deployments have exactly one owner. Never guess ownership of populated
    # pre-auth databases: provision the existing owner before migrating those databases.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM files")) and not connection.scalar(
        sa.text("SELECT count(*) FROM owners WHERE id = 1")
    ):
        raise RuntimeError("Provision the single owner before migrating existing files")
    op.create_table("folders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("owners.id"), nullable=False),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("folders.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_folders_parent_id", "folders", ["parent_id"])
    op.create_index("uq_folder_siblings", "folders",
                    ["owner_id", sa.text("coalesce(parent_id, '')"), sa.text("lower(name)")], unique=True)
    op.add_column("files", sa.Column("owner_id", sa.Integer(), server_default="1", nullable=False))
    op.add_column("files", sa.Column("folder_id", sa.String(36)))
    op.add_column("files", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("files") as batch:
        batch.create_foreign_key("fk_files_owner", "owners", ["owner_id"], ["id"])
        batch.create_foreign_key("fk_files_folder", "folders", ["folder_id"], ["id"])
        batch.create_index("ix_files_folder_id", ["folder_id"])
        batch.create_index("ix_files_deleted_at", ["deleted_at"])
    op.create_table("file_shares",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_file_shares_file_id", "file_shares", ["file_id"])


def downgrade():
    # A silent downgrade would lose trash/share/folder metadata. Restore a backup
    # deliberately instead of discarding that information during an interview demo.
    raise RuntimeError("Data-preserving migration: restore the pre-upgrade backup to roll back")
