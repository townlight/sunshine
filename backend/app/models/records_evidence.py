"""Typed Records evidence absent from the original web schema.

Human source-segment decisions are not invented document chunks or automatic
exemption flags. Ordered notes preserve the accepted desktop arrays losslessly.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.user import Base


class RequestEvidenceNote(Base):
    __tablename__ = "request_evidence_notes"
    __table_args__ = (CheckConstraint(
        "kind IN ('clarification','search','exemption','citation','approval','export')",
        name="records_evidence_note_kind",
    ),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("records_requests.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RequestExemptionDecision(Base):
    __tablename__ = "request_exemption_decisions"
    __table_args__ = (CheckConstraint(
        "decision IN ('release','redact','exempt')", name="records_segment_decision"
    ),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("records_requests.id", ondelete="CASCADE"), index=True
    )
    flag_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exemption_flags.id"))
    legacy_id: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    finding: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(Text)
    reviewer_label: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
