"""Initial empty archive, including transactional review and immutable content."""
from alembic import op

from backend.app.db import models  # noqa: F401
from backend.app.db.base import Base

revision = "0001_archive"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())
    protected = {
        "versions": ("id", "attempt_id", "version_no", "parent_version_id", "manifest", "manifest_hash", "change_note", "created_at"),
        "attempts": ("id", "prompt_id", "prompt_snapshot", "snapshot_hash", "created_at"),
        "evaluations": ("id", "version_id", "manifest_hash", "prompt_snapshot_hash", "payload_schema_version", "payload", "source", "supersedes_id", "created_at"),
        "assets": ("id", "sha256", "mime", "byte_size", "storage_key", "page_count", "created_by", "created_at", "original_name"),
        "asset_pages": ("id", "asset_id", "source_page", "preview_key", "width", "height"),
        "review_operations": ("id", "credential_id", "kind", "source_actor", "request_id", "original_digest", "original_payload", "target_snapshot", "created_at"),
    }
    for table, columns in protected.items():
        condition = " OR ".join(f"OLD.{col} IS NOT NEW.{col}" for col in columns)
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} WHEN {condition} "
                   "BEGIN SELECT RAISE(ABORT, 'immutable_content'); END")
    for table in ("versions", "attempts", "evaluations", "review_operations", "review_revisions", "review_decisions", "audit_events"):
        op.execute(f"CREATE TRIGGER retain_{table} BEFORE DELETE ON {table} "
                   "BEGIN SELECT RAISE(ABORT, 'retained_history'); END")
    for table in ("review_revisions", "review_decisions", "audit_events"):
        op.execute(f"CREATE TRIGGER append_only_{table} BEFORE UPDATE ON {table} "
                   "BEGIN SELECT RAISE(ABORT, 'immutable_history'); END")


def downgrade():
    raise RuntimeError("Destructive downgrade is disabled; restore a consistent backup instead")
