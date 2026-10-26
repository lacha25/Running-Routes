"""Environment loading and shared constants."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    google_maps_api_key: str | None
    telegram_bot_token: str | None
    db_path: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            db_path=os.getenv("DB_PATH", "./runorwalk.db"),
        )


# Algorithm constants
MIN_SAVINGS_S: float = 5 * 60  # only suggest running if it saves >= 5 minutes
MIN_RUN_DURATION_S: float = 120  # don't bother running on walks shorter than this
MAX_RUN_DISTANCE_M: float = 800  # don't propose runs longer than this
DEFAULT_MAX_RUN_MINUTES: float = 5  # cumulative run budget per trip
