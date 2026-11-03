import uuid
from datetime import datetime, date
from pydantic import BaseModel


class FeeScheduleCreate(BaseModel):
    jurisdiction: str
    fee_type: str
    amount: float
    description: str | None = None
    effective_date: date | None = None


class FeeScheduleRead(BaseModel):
    id: uuid.UUID
    jurisdiction: str
    fee_type: str
    amount: float
    description: str | None
    effective_date: date | None
    created_by: uuid.UUID | None
    created_at: datetime
    model_config = {"from_attributes": True}


class FeeScheduleUpdate(BaseModel):
    fee_type: str | None = None
    amount: float | None = None
    description: str | None = None
    effective_date: date | None = None
