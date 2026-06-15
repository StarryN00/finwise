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
    moonshot_model: str = "moonshot-v1-32k"
    moonshot_report_model: str = "moonshot-v1-8k"
    moonshot_timeout_seconds: int = 240
    ai_match_confidence_threshold: int = 90
    finwise_auth_enabled: bool = False
    finwise_admin_username: str = "admin"
    finwise_admin_password_hash: str = ""
    finwise_password_hash_file: str = ""
    finwise_jwt_secret: str = ""
    finwise_token_expire_hours: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()
