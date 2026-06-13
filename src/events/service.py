import json
from datetime import datetime, timezone

from src.database import redis_client


async def queue_event(event_data: dict) -> None:
    if event_data.get("created_at") is None:
        event_data["created_at"] = datetime.now(timezone.utc).isoformat()
    else:
        event_data["created_at"] = event_data["created_at"].isoformat()

    json_str = json.dumps(event_data)
    await redis_client.rpush("queue:events", json_str)
