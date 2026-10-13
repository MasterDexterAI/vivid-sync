import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "models" / "silero_vad.onnx"


def main():
    spec = importlib.util.find_spec("silero_vad")
    if spec is None or not spec.submodule_search_locations:
        sys.exit("silero-vad is not installed. Run: pip install silero-vad --no-deps")
    source = Path(list(spec.submodule_search_locations)[0]) / "data" / "silero_vad.onnx"
    if not source.exists():
        sys.exit(f"Model not found at {source}")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, TARGET)
    print(f"Copied {source.name} ({source.stat().st_size // 1024} KB) to {TARGET}")


if __name__ == "__main__":
    main()
