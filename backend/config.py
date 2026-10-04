import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "waveguard.db")
    serial_port: str = os.getenv("SERIAL_PORT", "")
    serial_baud_rate: int = int(os.getenv("SERIAL_BAUD_RATE", "115200"))
    reference_distance_cm: float = float(os.getenv("REFERENCE_DISTANCE_CM", "20.0"))


settings = Settings()
