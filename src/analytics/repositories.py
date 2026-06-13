from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.models import Event


async def get_summary(session: AsyncSession, company_id: int, start_date: date, end_date: date) -> dict:
    date_filter = (
        Event.company_id == company_id,
        Event.created_at >= start_date,
        Event.created_at <= end_date,
    )

    total_users_q = await session.execute(
        select(func.count(func.distinct(Event.user_id))).where(*date_filter)
    )
    total_users = total_users_q.scalar()

    total_events_q = await session.execute(
        select(func.count()).select_from(Event).where(*date_filter)
    )
    total_events = total_events_q.scalar()

    query = (
        select(
            Event.event_type,
            func.count(func.distinct(Event.user_id)).label("unique_users"),
            func.count().label("total_events"),
        )
        .where(*date_filter)
        .group_by(Event.event_type)
    )
    result = await session.execute(query)
    rows = result.all()

    events_summary = [
        {"event_type": row.event_type, "unique_users": row.unique_users, "total_events": row.total_events}
        for row in rows
    ]

    return {
        "company_id": company_id,
        "total_users": total_users,
        "total_events": total_events,
        "events": events_summary,
    }
