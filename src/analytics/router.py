from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.schemas import SummaryResponse
from src.analytics.service import get_cached_summary
from src.auth.dependencies import get_current_active_user, get_db
from src.auth.models import User
from src.database import redis_client

router = APIRouter()


@router.get("/summary/", response_model=SummaryResponse)
async def summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if start_date > end_date:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="start_date must be before end_date")
    result = await get_cached_summary(
        redis_client, db, current_user.company_id, start_date, end_date
    )
    return result
