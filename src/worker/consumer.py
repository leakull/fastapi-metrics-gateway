import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database import async_session, redis_client
from src.events.models import Event
from src.metrics import events_inserted_total
from src.worker.config import BATCH_INTERVAL, BATCH_SIZE, PROCESSING_KEY, QUEUE_KEY

logger = logging.getLogger(__name__)


def _parse(raw: str) -> dict:
    data = json.loads(raw)
    if isinstance(data.get("id"), str):
        data["id"] = uuid.UUID(data["id"])
    if isinstance(data.get("created_at"), str):
        dt = datetime.fromisoformat(data["created_at"])
        # Columns are timestamptz; always hand asyncpg a timezone-aware UTC value.
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        data["created_at"] = dt
    return data


async def _drain_batch() -> list[str]:
    """Reliably move up to BATCH_SIZE items from the queue into the processing list.

    LMOVE is atomic, so an item is never lost in the gap between read and ack:
    it lives in the processing list until the batch is committed and acknowledged.
    """
    raw_items: list[str] = []
    for _ in range(BATCH_SIZE):
        item = await redis_client.lmove(QUEUE_KEY, PROCESSING_KEY, "left", "right")
        if item is None:
            break
        raw_items.append(item)
    return raw_items


async def _restore_processing() -> None:
    """Move any in-flight items back to the head of the queue, preserving order.

    Used both for crash recovery on startup and to retry a batch whose insert failed.
    """
    restored = 0
    while await redis_client.lmove(PROCESSING_KEY, QUEUE_KEY, "right", "left") is not None:
        restored += 1
    if restored:
        logger.info("Restored %d in-flight events back to the queue", restored)


async def consumer_loop():
    logger.info("Consumer started")
    # Recover items left in the processing list by a previously crashed run.
    await _restore_processing()
    while True:
        try:
            raw_items = await _drain_batch()
            if not raw_items:
                await asyncio.sleep(BATCH_INTERVAL)
                continue

            items = [_parse(raw) for raw in raw_items]

            try:
                async with async_session() as session:
                    # ON CONFLICT DO NOTHING makes reprocessing the same batch idempotent:
                    # an event that was already committed before a crash is silently skipped.
                    stmt = pg_insert(Event).on_conflict_do_nothing(index_elements=["id"])
                    await session.execute(stmt, items)
                    await session.commit()
                # Commit succeeded: acknowledge by dropping the processing list.
                await redis_client.delete(PROCESSING_KEY)
                events_inserted_total.inc(len(items))
                logger.info("Inserted %d events", len(items))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Consumer error, restoring batch for retry")
                await _restore_processing()

            await asyncio.sleep(BATCH_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Consumer shutting down gracefully")
            break
