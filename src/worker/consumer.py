import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import insert

from src.database import async_session, redis_client
from src.events.models import Event
from src.worker.config import BATCH_INTERVAL, BATCH_SIZE, QUEUE_KEY

logger = logging.getLogger(__name__)


async def consumer_loop():
    logger.info("Consumer started")
    while True:
        try:
            raw_items = await redis_client.lrange(QUEUE_KEY, 0, BATCH_SIZE - 1)
            if not raw_items:
                await asyncio.sleep(BATCH_INTERVAL)
                continue

            items = []
            for raw in raw_items:
                data = json.loads(raw)
                if isinstance(data.get("created_at"), str):
                    dt = datetime.fromisoformat(data["created_at"])
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(timezone.utc)
                    data["created_at"] = dt.replace(tzinfo=None)
                items.append(data)

            try:
                async with async_session() as session:
                    await session.execute(insert(Event), items)
                    await session.commit()
                    await redis_client.ltrim(QUEUE_KEY, len(raw_items), -1)
                    logger.info("Inserted %d events", len(items))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Consumer error, will retry next cycle")

            await asyncio.sleep(BATCH_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Consumer shutting down gracefully")
            break
