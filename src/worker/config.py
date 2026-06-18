from src.config import settings

BATCH_INTERVAL = settings.BATCH_INTERVAL
BATCH_SIZE = settings.BATCH_SIZE
QUEUE_KEY = "queue:events"
PROCESSING_KEY = "queue:events:processing"
HEARTBEAT_KEY = "heartbeat:worker:last_processed_at"
HEARTBEAT_TTL = 60  # seconds
