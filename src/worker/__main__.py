import asyncio
import logging

from prometheus_client import start_http_server

from src.database import engine, redis_client
from src.observability import setup_logging
from src.worker.consumer import consumer_loop

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    # Expose consumer metrics (events_inserted_total, ...) for Prometheus to scrape.
    start_http_server(9100)
    logger.info("Worker metrics server listening on :9100")
    try:
        await consumer_loop()
    finally:
        await engine.dispose()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
