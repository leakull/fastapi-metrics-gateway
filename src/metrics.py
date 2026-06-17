from prometheus_client import Counter, Histogram

events_enqueued_total = Counter(
    "events_enqueued_total", "Events accepted into the Redis queue"
)
events_inserted_total = Counter(
    "events_inserted_total", "Events persisted to PostgreSQL by the consumer"
)
analytics_cache_hits_total = Counter(
    "analytics_cache_hits_total", "Analytics summary requests served from cache"
)
analytics_cache_misses_total = Counter(
    "analytics_cache_misses_total", "Analytics summary requests computed from the database"
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "status"],
)
