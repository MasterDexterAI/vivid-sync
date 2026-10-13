import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _optional_int(name: str):
    value = os.getenv(name, "").strip()
    return int(value) if value else None


@dataclass(frozen=True)
class ClientSettings:
    server_url: str = os.getenv("SERVER_URL", "ws://127.0.0.1:8000/ws")
    audio_device: int | None = _optional_int("AUDIO_DEVICE")
    monitor: int = int(os.getenv("MONITOR", "1"))
    screen_hz: float = float(os.getenv("SCREEN_HZ", "2"))
    delta_threshold: float = float(os.getenv("DELTA_THRESHOLD", "0.015"))
    min_frame_interval: float = float(os.getenv("MIN_FRAME_INTERVAL", "1.0"))
    jpeg_quality: int = int(os.getenv("JPEG_QUALITY", "75"))
    hide_from_capture: bool = os.getenv("HIDE_FROM_CAPTURE", "true").lower() == "true"


settings = ClientSettings()
