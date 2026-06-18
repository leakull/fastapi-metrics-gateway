#!/usr/bin/env python3
"""Healthcheck script for the worker service.

Checks that the worker has written a heartbeat to Redis within the last 120 seconds.
Used by docker-compose healthcheck.
"""
import os
import sys
from datetime import datetime, timezone

import redis

HEARTBEAT_KEY = "heartbeat:worker:last_processed_at"
MAX_AGE_SECONDS = 120


def main() -> int:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        r = redis.from_url(redis_url, decode_responses=True, socket_timeout=3)
        raw = r.get(HEARTBEAT_KEY)
    except Exception:
        return 1

    if not raw:
        return 1

    try:
        hb_time = datetime.fromisoformat(raw)
        if hb_time.tzinfo is None:
            hb_time = hb_time.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - hb_time).total_seconds()
        return 0 if age < MAX_AGE_SECONDS else 1
    except (ValueError, TypeError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
