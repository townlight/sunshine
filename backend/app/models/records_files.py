"""Lossless native file evidence linked to the existing document domain."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.user import Base


class RequestFileEvidence(Base):
    __tablename__ = "request_file_evidence"

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("request_documents.id"), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records_requests.id"), index=True)
    legacy_id: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    original_path: Mapped[str] = mapped_column(Text)
    citation: Mapped[str] = mapped_column(Text)
    added_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RequestReleaseCopy(Base):
    __tablename__ = "request_release_copies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records_requests.id"), index=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("request_file_evidence.id"), index=True)
    original_path: Mapped[str] = mapped_column(Text)
    stored_path: Mapped[str] = mapped_column(Text, unique=True)
    file_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text)
    added_by: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
