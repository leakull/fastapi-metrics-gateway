import logging

from pydantic import model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://analytics:analytics@localhost:5434/analytics"
    REDIS_URL: str = "redis://localhost:6381/0"
    JWT_SECRET: str = "super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 30
    BATCH_INTERVAL: int = 5
    BATCH_SIZE: int = 1000

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def _check_secret(self):
        if self.JWT_SECRET == "super-secret-key-change-in-production":
            logger.warning("JWT_SECRET is the default value - change it in production!")
        return self


settings = Settings()
