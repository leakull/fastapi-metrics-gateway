from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config import settings

# A single shared limiter instance. It must be the same object that is registered
# on app.state and used by every route decorator, otherwise the limits silently
# do nothing. Redis storage makes limits shared across multiple API replicas.
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)
