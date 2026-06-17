from fastapi import APIRouter, Depends, Request, status

from src.auth.dependencies import get_current_active_user
from src.auth.models import User
from src.events.schemas import EventAccepted, EventCreate
from src.events.service import queue_event
from src.limiter import limiter

router = APIRouter()


@router.post("/", response_model=EventAccepted, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("1000/minute")
async def create_event(
    request: Request,
    event_data: EventCreate,
    current_user: User = Depends(get_current_active_user),
):
    event_dict = event_data.model_dump()
    event_dict["company_id"] = current_user.company_id
    event_id = await queue_event(event_dict)
    return EventAccepted(event_id=event_id)
