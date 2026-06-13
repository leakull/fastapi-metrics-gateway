import json
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.repositories import get_summary
from src.database import redis_client


async def get_cached_summary(
    redis, session: AsyncSession, company_id: int, start_date: date, end_date: date
) -> dict:
    cache_key = f"cache:analytics:{company_id}:{start_date}:{end_date}"

    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    result = await get_summary(session, company_id, start_date, end_date)
    await redis.set(cache_key, json.dumps(result), ex=300)
    return result
