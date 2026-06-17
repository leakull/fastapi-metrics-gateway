from slowapi import Limiter
from slowapi.util import get_remote_address

# A single shared limiter instance. It must be the same object that is registered
# on app.state and used by every route decorator, otherwise the limits silently
# do nothing. In-memory storage is fine for a single API replica; for several
# replicas point slowapi at Redis via `storage_uri`.
limiter = Limiter(key_func=get_remote_address)
