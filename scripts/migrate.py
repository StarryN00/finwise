from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.db import Database


if __name__ == "__main__":
    settings = Settings.from_env(Path(__file__).resolve().parents[1])
    database = Database(settings)
    database.initialize()
    print(f"迁移完成：{settings.database_path}")
