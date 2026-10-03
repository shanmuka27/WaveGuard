import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "waveguard.db")
    serial_port: str = os.getenv("SERIAL_PORT", "")
    serial_baud_rate: int = int(os.getenv("SERIAL_BAUD_RATE", "115200"))
    reference_distance_cm: float = float(os.getenv("REFERENCE_DISTANCE_CM", "20.0"))


settings = Settings()
