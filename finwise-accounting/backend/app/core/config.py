from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "FinWise Accounting"
    database_url: str = "sqlite:///./finwise_accounting.db"
    upload_dir: Path = Path("storage/uploads")
    default_organization_id: str = "00000000-0000-0000-0000-000000000001"
    enable_ai: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
