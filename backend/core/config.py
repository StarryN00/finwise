import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
FILES_DIR = DATA_DIR / "files"
FILES_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_CHANNEL_ID = "00000000-0000-0000-0000-000000000001"


class Settings(BaseSettings):
    # App
    APP_NAME: str = "智税管家"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    DEFAULT_CHANNEL_ID: str = DEFAULT_CHANNEL_ID
    IMPORT_DIRECTORY_ALLOWLIST: str = os.environ.get("IMPORT_DIRECTORY_ALLOWLIST", "/Volumes/共享文件夹/财务项目")

    # Database
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/finwise"
    )
    DB_ECHO: bool = False

    # JWT
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # File Storage
    FILES_DIR: Path = FILES_DIR
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB

    # AI Providers
    # MiniMax
    MINIMAX_API_KEY: str = os.environ.get("MINIMAX_API_KEY", "")
    MINIMAX_BASE_URL: str = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
    MINIMAX_MODEL: str = os.environ.get("MINIMAX_MODEL", "MiniMax-Text-01")

    # Moonshot (Kimi)
    MOONSHOT_API_KEY: str = os.environ.get("MOONSHOT_API_KEY", "")
    MOONSHOT_BASE_URL: str = os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
    MOONSHOT_MODEL: str = os.environ.get("MOONSHOT_MODEL", "moonshot-v1-32k")

    # Active AI provider: "minimax" or "moonshot"
    ACTIVE_AI_PROVIDER: Literal["minimax", "moonshot"] = "minimax"

    # AI Model Selection by scenario
    AI_BANK_PARSING_MODEL: str = "MiniMax-Text-01"  # Cost-efficient for structured tasks
    AI_MATCHING_MODEL: str = "MiniMax-Text-01"  # Candidate recommendation
    AI_ANALYSIS_MODEL: str = "MiniMax-Text-01"  # Complex analysis

    class Config:
        env_file = ".env.local"
        case_sensitive = True
        extra = "allow"


settings = Settings()
