import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    realtime_model: str = os.getenv("REALTIME_MODEL", "gpt-realtime-2.1")
    realtime_url: str = os.getenv("REALTIME_URL", "wss://api.openai.com/v1/realtime")
    transcribe_model: str = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-transcribe")
    vad_model_path: str = os.getenv("VAD_MODEL_PATH", str(ROOT / "models" / "silero_vad.onnx"))
    vad_start: float = float(os.getenv("VAD_START", "0.5"))
    vad_end: float = float(os.getenv("VAD_END", "0.35"))
    vad_silence_ms: int = int(os.getenv("VAD_SILENCE_MS", "350"))
    min_turn_ms: int = int(os.getenv("MIN_TURN_MS", "600"))
    barge_in: bool = os.getenv("BARGE_IN", "true").lower() == "true"
    knowledge_path: str = os.getenv("KNOWLEDGE_PATH", str(ROOT / "knowledge" / "facts.md"))


settings = Settings()
