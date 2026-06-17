import json
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.repositories import get_summary
from src.metrics import analytics_cache_hits_total, analytics_cache_misses_total


async def get_cached_summary(
    redis, session: AsyncSession, company_id: int, start_date: date, end_date: date
) -> dict:
    # A range that reaches today is still mutable — new events keep arriving — so caching
    # it would serve stale numbers for up to the TTL. Only cache closed past ranges.
    today = datetime.now(timezone.utc).date()
    if end_date >= today:
        analytics_cache_misses_total.inc()
        return await get_summary(session, company_id, start_date, end_date)

    cache_key = f"cache:analytics:{company_id}:{start_date}:{end_date}"

    cached = await redis.get(cache_key)
    if cached:
        analytics_cache_hits_total.inc()
        return json.loads(cached)

    analytics_cache_misses_total.inc()
    result = await get_summary(session, company_id, start_date, end_date)
    await redis.set(cache_key, json.dumps(result), ex=300)
    return result
