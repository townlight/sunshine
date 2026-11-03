# backend/app/schemas/sync_failure.py
"""Pydantic schemas for sync_failures and sync_run_log API responses."""
import uuid
from datetime import datetime
from pydantic import BaseModel


class SyncFailureRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_path: str
    error_message: str | None
    error_class: str | None
    http_status_code: int | None
    retry_count: int
    status: str
    first_failed_at: datetime
    last_retried_at: datetime | None
    dismissed_at: datetime | None
    dismissed_by: uuid.UUID | None
    model_config = {"from_attributes": True}


class SyncRunLogRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None
    status: str | None
    records_attempted: int
    records_succeeded: int
    records_failed: int
    error_summary: str | None
    model_config = {"from_attributes": True}
