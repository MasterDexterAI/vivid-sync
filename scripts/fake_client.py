import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.test_vad import load_wav_24k
from server.vad import INPUT_FRAME, INPUT_RATE

SERVER = "ws://127.0.0.1:8000/ws"


async def main(wav_path: str, image_path: str | None):
    audio = load_wav_24k(wav_path)
    tail = np.zeros(INPUT_RATE * 4, dtype=np.int16)
    audio = np.concatenate([audio, tail])
    latencies = []
    async with websockets.connect(SERVER, max_size=None) as ws:
        async def listen():
            async for raw in ws:
                ev = json.loads(raw)
                if ev["type"] == "latency":
                    latencies.append(ev["ttft_ms"])
                if ev["type"] == "delta":
                    print(ev["text"], end="", flush=True)
                else:
                    print(f"\n[{ev['type']}] {json.dumps({k: v for k, v in ev.items() if k != 'type'})}")

        listener = asyncio.create_task(listen())
        if image_path:
            jpeg = Path(image_path).read_bytes()
            await ws.send(json.dumps({"type": "frame", "jpeg": base64.b64encode(jpeg).decode("ascii")}))
        start = time.perf_counter()
        for n, i in enumerate(range(0, len(audio) - INPUT_FRAME + 1, INPUT_FRAME)):
            await ws.send(audio[i:i + INPUT_FRAME].tobytes())
            await asyncio.sleep(max(0.0, start + (n + 1) * 0.032 - time.perf_counter()))
        await asyncio.sleep(3)
        listener.cancel()
    if latencies:
        print(f"\nTime to first token after end of speech: {latencies} ms. Median {int(np.median(latencies))} ms.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m scripts.fake_client path/to/speech.wav [path/to/screenshot.jpg]")
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
