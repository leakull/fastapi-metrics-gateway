import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

MAX_PAYLOAD_BYTES = 65_536  # 64 KB


class EventCreate(BaseModel):
    # Optional client-supplied idempotency key. Retrying with the same event_id is a
    # no-op (the consumer inserts with ON CONFLICT DO NOTHING). If omitted, the server
    # generates one and returns it so the client can retry safely.
    event_id: uuid.UUID | None = None
    company_id: int | None = None
    user_id: str = Field(max_length=255)
    event_type: str = Field(max_length=255)
    payload: dict = {}
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _check_payload_size(self):
        size = len(json.dumps(self.payload).encode())
        if size > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes ({size} bytes)")
        return self


class EventAccepted(BaseModel):
    status: str = "queued"
    event_id: uuid.UUID
