"""Relational archive and review records. JSON holds bounded immutable documents."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Table, Text, UniqueConstraint

from .base import Base


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def now():
    return datetime.now(timezone.utc).isoformat()


prompt_categories = Table("prompt_categories", Base.metadata,
    Column("prompt_id", ForeignKey("prompts.id"), primary_key=True),
    Column("category_id", ForeignKey("categories.id"), primary_key=True))


class Category(Base):
    __tablename__ = "categories"
    id = Column(String, primary_key=True, default=lambda: uid("cat"))
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    language_scope = Column(String, nullable=False, default="all")
    sort_order = Column(Integer, nullable=False, default=0)
    archived_at = Column(String)
    revision = Column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("language_scope", "normalized_name"),)


class Prompt(Base):
    __tablename__ = "prompts"
    id = Column(String, primary_key=True, default=lambda: uid("prm"))
    title = Column(String, nullable=False)
    language = Column(String, nullable=False)
    instructions = Column(Text, nullable=False, default="")
    requirements = Column(Text, nullable=False, default="")
    source_note = Column(Text, nullable=False, default="")
    rubric = Column(JSON)
    materials = Column(JSON, nullable=False, default=list)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False, default=now)


class Attempt(Base):
    __tablename__ = "attempts"
    id = Column(String, primary_key=True, default=lambda: uid("att"))
    prompt_id = Column(String, ForeignKey("prompts.id"), nullable=False, index=True)
    prompt_snapshot = Column(JSON, nullable=False)
    snapshot_hash = Column(String, nullable=False)
    written_at = Column(String)
    duration_minutes = Column(Integer)
    reflection = Column(Text, nullable=False, default="")
    selected_version_id = Column(String, ForeignKey("versions.id", use_alter=True))
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False, default=now)


class Version(Base):
    __tablename__ = "versions"
    id = Column(String, primary_key=True, default=lambda: uid("ver"))
    attempt_id = Column(String, ForeignKey("attempts.id"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    parent_version_id = Column(String, ForeignKey("versions.id"))
    manifest = Column(JSON, nullable=False)
    manifest_hash = Column(String, nullable=False)
    change_note = Column(Text, nullable=False, default="")
    created_at = Column(String, nullable=False, default=now)
    voided_at = Column(String)
    __table_args__ = (UniqueConstraint("attempt_id", "version_no"),)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id = Column(String, primary_key=True, default=lambda: uid("evl"))
    version_id = Column(String, ForeignKey("versions.id"), nullable=False, index=True)
    manifest_hash = Column(String, nullable=False)
    prompt_snapshot_hash = Column(String, nullable=False)
    payload_schema_version = Column(Integer, nullable=False, default=1)
    payload = Column(JSON, nullable=False)
    source = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=now)
    supersedes_id = Column(String, ForeignKey("evaluations.id"))
    voided_at = Column(String)


class Asset(Base):
    __tablename__ = "assets"
    id = Column(String, primary_key=True, default=lambda: uid("ast"))
    sha256 = Column(String, nullable=False)
    mime = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    byte_size = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=False)
    storage_key = Column(String, nullable=False, unique=True)
    created_by = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=now)


class AssetPage(Base):
    __tablename__ = "asset_pages"
    id = Column(String, primary_key=True, default=lambda: uid("pg"))
    asset_id = Column(String, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    source_page = Column(Integer, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    preview_key = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("asset_id", "source_page"),)


class FileReference(Base):
    __tablename__ = "file_references"
    owner_type = Column(String, primary_key=True)
    owner_id = Column(String, primary_key=True)
    asset_id = Column(String, ForeignKey("assets.id"), primary_key=True)


class ReviewOperation(Base):
    __tablename__ = "review_operations"
    id = Column(String, primary_key=True, default=lambda: uid("op"))
    kind = Column(String, nullable=False)
    source_actor = Column(String, nullable=False)
    credential_id = Column(String, ForeignKey("credentials.id"), nullable=False)
    request_id = Column(String, nullable=False)
    original_payload = Column(JSON, nullable=False)
    payload = Column(JSON, nullable=False)
    original_digest = Column(String, nullable=False)
    effective_digest = Column(String, nullable=False)
    target_snapshot = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="pending", index=True)
    result = Column(JSON)
    created_at = Column(String, nullable=False, default=now)
    __table_args__ = (UniqueConstraint("credential_id", "kind", "request_id"),)


class ReviewRevision(Base):
    __tablename__ = "review_revisions"
    id = Column(String, primary_key=True, default=lambda: uid("rr"))
    operation_id = Column(String, ForeignKey("review_operations.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    digest = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=now)
    __table_args__ = (UniqueConstraint("operation_id", "revision"),)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    id = Column(String, primary_key=True, default=lambda: uid("rd"))
    operation_id = Column(String, ForeignKey("review_operations.id"), nullable=False, unique=True)
    review_revision = Column(Integer, nullable=False)
    decision = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    decided_at = Column(String, nullable=False, default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(String, primary_key=True, default=lambda: uid("aud"))
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False)
    entity_refs = Column(JSON, nullable=False, default=dict)
    operation_id = Column(String, ForeignKey("review_operations.id"))
    result = Column(JSON, nullable=False)
    created_at = Column(String, nullable=False, default=now)


class Credential(Base):
    __tablename__ = "credentials"
    id = Column(String, primary_key=True, default=lambda: uid("key"))
    name = Column(String, nullable=False)
    secret_hash = Column(String, nullable=False, unique=True)
    scopes = Column(JSON, nullable=False)
    expires_at = Column(String)
    revoked_at = Column(String)
    last_used_at = Column(String)
    created_at = Column(String, nullable=False, default=now)


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: uid("usr"))
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)


class WebSession(Base):
    __tablename__ = "web_sessions"
    id_hash = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    expires_at = Column(String, nullable=False)
    csrf_state = Column(String, nullable=False)


class ReadReceipt(Base):
    __tablename__ = "read_receipts"
    id = Column(String, primary_key=True, default=lambda: uid("read"))
    credential_id = Column(String, ForeignKey("credentials.id"), nullable=False)
    version_id = Column(String, ForeignKey("versions.id"))
    page_ids = Column(JSON, nullable=False)
    created_at = Column(String, nullable=False, default=now)
