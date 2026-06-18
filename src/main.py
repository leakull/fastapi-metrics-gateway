from contextlib import asynccontextmanager
import asyncio

from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from src.database import async_session, engine, get_redis, close_redis
from src.exceptions import AppException
from src.limiter import limiter
from src.observability import RequestContextMiddleware, setup_logging
from src.worker.config import HEARTBEAT_KEY, HEARTBEAT_TTL, QUEUE_KEY
from src.auth.router import router as auth_router
from src.events.router import router as events_router
from src.analytics.router import router as analytics_router

setup_logging()

_inflight_requests = 0
_shutdown_event = asyncio.Event()


class GracefulShutdownMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global _inflight_requests
        if _shutdown_event.is_set():
            return JSONResponse(status_code=503, content={"detail": "Server is shutting down"})
        _inflight_requests += 1
        try:
            return await call_next(request)
        finally:
            _inflight_requests -= 1


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _shutdown_event.set()
    while _inflight_requests > 0:
        await asyncio.sleep(0.1)
    await engine.dispose()
    await close_redis()


app = FastAPI(title="Analytics Gateway", lifespan=lifespan)
app.add_middleware(GracefulShutdownMiddleware)
app.add_middleware(RequestContextMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(events_router, prefix="/api/v1/events", tags=["events"])
app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["analytics"])


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    try:
        redis = get_redis()
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
            await session.commit()
        await redis.ping()
        queue_depth = await redis.llen(QUEUE_KEY)

        worker_alive = False
        try:
            last_heartbeat = await redis.get(HEARTBEAT_KEY)
            if last_heartbeat:
                hb_time = datetime.fromisoformat(last_heartbeat)
                if hb_time.tzinfo is None:
                    hb_time = hb_time.replace(tzinfo=timezone.utc)
                worker_alive = (datetime.now(timezone.utc) - hb_time).total_seconds() < HEARTBEAT_TTL
        except Exception:
            pass
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy"})
    return {"status": "ok", "queue_depth": queue_depth, "worker": "ok" if worker_alive else "dead"}
