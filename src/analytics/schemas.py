from datetime import date

from pydantic import BaseModel


class EventStats(BaseModel):
    event_type: str
    unique_users: int
    total_events: int


class SummaryResponse(BaseModel):
    company_id: int
    total_users: int
    total_events: int
    events: list[EventStats]
