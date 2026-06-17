import json
import uuid
from datetime import datetime, timezone

from src.database import redis_client
from src.metrics import events_enqueued_total
from src.worker.config import QUEUE_KEY


async def queue_event(event_data: dict) -> uuid.UUID:
    # The primary key is assigned here, at enqueue time, so it stays stable across any
    # consumer-side reprocessing — that is what makes ON CONFLICT dedup effective.
    event_id = event_data.pop("event_id", None) or uuid.uuid4()
    event_data["id"] = str(event_id)

    if event_data.get("created_at") is None:
        event_data["created_at"] = datetime.now(timezone.utc).isoformat()
    else:
        event_data["created_at"] = event_data["created_at"].isoformat()

    await redis_client.rpush(QUEUE_KEY, json.dumps(event_data))
    events_enqueued_total.inc()
    return event_id
