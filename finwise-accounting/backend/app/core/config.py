from functools import lru_cache
from pathlib import Path

from pydantic_settings import SettingsConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env", "../../.env.local", ".env.local"),
        extra="ignore",
    )

    app_name: str = "FinWise Accounting"
    database_url: str = "sqlite:///./finwise_accounting.db"
    upload_dir: Path = Path("storage/uploads")
    default_organization_id: str = "00000000-0000-0000-0000-000000000001"
    enable_ai: bool = False
    moonshot_api_key: str = ""
    moonshot_base_url: str = "https://api.moonshot.cn/v1"
    moonshot_model: str = "kimi-k2.6"
    ai_match_confidence_threshold: int = 90


@lru_cache
def get_settings() -> Settings:
    return Settings()
