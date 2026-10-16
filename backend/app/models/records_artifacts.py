"""Immutable export intents and completed Records artifacts, not workflow state."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.user import Base


class RequestArtifact(Base):
    __tablename__ = "request_artifacts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records_requests.id"), index=True)
    legacy_id: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    response_sha256: Mapped[str] = mapped_column(Text)
    export_path: Mapped[str | None] = mapped_column(Text, unique=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    document_count: Mapped[int] = mapped_column(Integer)
    release_artifact_count: Mapped[int] = mapped_column(Integer)
    search_session_count: Mapped[int] = mapped_column(Integer)
    release_count: Mapped[int] = mapped_column(Integer)
    redacted_count: Mapped[int] = mapped_column(Integer)
    exempt_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestPublication(Base):
    __tablename__ = "request_publications"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records_requests.id"), index=True)
    legacy_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
