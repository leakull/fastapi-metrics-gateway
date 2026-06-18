import json
import logging
import uuid
from datetime import datetime, timezone

from src.database import get_redis
from src.exceptions import AppException
from src.metrics import events_enqueued_total
from src.worker.config import QUEUE_KEY

logger = logging.getLogger(__name__)


async def queue_event(event_data: dict) -> uuid.UUID:
    # The primary key is assigned here, at enqueue time, so it stays stable across any
    # consumer-side reprocessing — that is what makes ON CONFLICT dedup effective.
    event_id = event_data.pop("event_id", None) or uuid.uuid4()
    event_data["id"] = str(event_id)

    if event_data.get("created_at") is None:
        event_data["created_at"] = datetime.now(timezone.utc).isoformat()
    else:
        event_data["created_at"] = event_data["created_at"].isoformat()

    try:
        await get_redis().rpush(QUEUE_KEY, json.dumps(event_data))
    except Exception:
        logger.exception("Failed to enqueue event to Redis")
        raise AppException(status_code=503, message="Event queue temporarily unavailable")

    events_enqueued_total.inc()
    return event_id
