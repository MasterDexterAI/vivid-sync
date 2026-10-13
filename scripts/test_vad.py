import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import settings
from server.vad import INPUT_FRAME, INPUT_RATE, SileroVAD, TurnDetector


def load_wav_24k(path: str) -> np.ndarray:
    rate, data = wavfile.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.dtype != np.int16:
        data = (data / np.abs(data).max() * 32767) if data.dtype.kind == "f" else data
    data = data.astype(np.float32)
    if rate != INPUT_RATE:
        data = resample_poly(data, INPUT_RATE, rate)
    return np.clip(data, -32768, 32767).astype(np.int16)


def record_24k(seconds: float) -> np.ndarray:
    import sounddevice as sd

    print(f"Recording {seconds}s. Talk, pause, talk again.")
    audio = sd.rec(int(seconds * INPUT_RATE), samplerate=INPUT_RATE, channels=1, dtype="int16")
    sd.wait()
    return audio[:, 0]


def main():
    audio = load_wav_24k(sys.argv[1]) if len(sys.argv) > 1 else record_24k(8)
    detector = TurnDetector(SileroVAD(settings.vad_model_path), settings.vad_start, settings.vad_end, settings.vad_silence_ms)
    timings = []
    for i in range(0, len(audio) - INPUT_FRAME + 1, INPUT_FRAME):
        frame = audio[i:i + INPUT_FRAME].tobytes()
        started = time.perf_counter()
        event = detector.feed(frame)
        timings.append((time.perf_counter() - started) * 1000)
        if event:
            print(f"{i / INPUT_RATE:6.2f}s  {event}  p={detector.last_prob:.2f}")
    print(f"\n{len(timings)} frames of 32 ms. VAD cost per frame: median {np.median(timings):.2f} ms, p95 {np.percentile(timings, 95):.2f} ms")


if __name__ == "__main__":
    main()
