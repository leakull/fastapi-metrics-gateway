from datetime import datetime

from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    company_id: int | None = None
    user_id: str = Field(max_length=255)
    event_type: str = Field(max_length=255)
    payload: dict = {}
    created_at: datetime | None = None


class EventAccepted(BaseModel):
    status: str = "queued"
