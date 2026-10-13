# 06. Run it and measure it

"Sub-500 ms" is a claim. Here is how you turn it into a number you can put on a slide.

## Where the 500 ms goes

From the moment a speaker stops talking to the first word on your HUD:

| Stage | What I measured or expect | Your knob |
|---|---|---|
| Silence hangover | 350 ms (config) | `VAD_SILENCE_MS` |
| VAD compute | 0.71 ms median per frame | none needed |
| Client to server | 5 to 30 ms on a good network | deploy region |
| Gateway overhead | about 5 ms | none needed |
| Model first token | 150 to 400 ms, varies | model choice, prompt size |
| HUD paint | a few ms | none needed |

Look at the first row. The VAD waits 350 ms before it is even allowed to say "turn over". That is most of your budget, gone before OpenAI hears anything.

So when people say "the model is slow", they are often measuring their own silence timer.

The `ttft_ms` the HUD shows starts the clock after the hangover. That is the honest number for the model and network. Add `VAD_SILENCE_MS` to it for the number a human feels.

Want the felt latency under 500 ms? Drop `VAD_SILENCE_MS` to 250 and keep the instructions short. Every KB in `facts.md` is prompt the model reads on every turn.

## Test 1: VAD on a recording

```bash
python scripts/test_vad.py
```

Records 8 seconds from your default mic. Talk, pause for a full second, talk again. Or pass any WAV file:

```bash
python scripts/test_vad.py path/to/clip.wav
```

`scripts/test_vad.py`:

```python
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
```

Expected output on a clip with two sentences:

```
  1.54s  speech_start  p=0.99
  6.56s  speech_end  p=0.02
  8.16s  speech_start  p=1.00
 11.42s  speech_end  p=0.01

401 frames of 32 ms. VAD cost per frame: median 0.71 ms, p95 1.12 ms
```

One start and one end per sentence. If you see five ends in one sentence, raise `VAD_SILENCE_MS`. If turns never end in a noisy room, raise `VAD_END` a little, to 0.4.

## Test 2: the screen filter

```bash
python scripts/test_screen_delta.py 30
```

`scripts/test_screen_delta.py`:

```python
import sys
import time
from pathlib import Path

import mss
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from client.config import settings
from client.screen import ScreenDeltaDetector


def main(seconds: float = 30.0):
    detector = ScreenDeltaDetector(settings.delta_threshold, settings.min_frame_interval, settings.jpeg_quality)
    captured, sent, total_bytes, grab_ms = 0, 0, 0, []
    print(f"Watching monitor {settings.monitor} for {seconds:.0f}s. Switch slides, scroll, sit still. Compare.")
    with mss.mss() as sct:
        area = sct.monitors[settings.monitor]
        end = time.time() + seconds
        while time.time() < end:
            started = time.perf_counter()
            bgr = np.asarray(sct.grab(area))[:, :, :3]
            jpeg = detector.evaluate(bgr, time.time())
            grab_ms.append((time.perf_counter() - started) * 1000)
            captured += 1
            if jpeg:
                sent += 1
                total_bytes += len(jpeg)
                print(f"  sent frame {sent}: delta {detector.last_ratio:.3f}, {len(jpeg) // 1024} KB")
            time.sleep(max(0.0, 1 / settings.screen_hz - (time.perf_counter() - started)))
    print(f"\nCaptured {captured}, sent {sent} ({sent / max(captured, 1):.0%}).")
    print(f"Capture plus filter: median {np.median(grab_ms):.1f} ms. Avg JPEG {total_bytes // max(sent, 1) // 1024} KB.")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 30.0)
```

For 30 seconds: sit still, then scroll a doc, then flip slides. You want almost nothing sent while you sit still, a frame per real change, and capture plus filter under about 30 ms. If scrolling floods frames, raise `MIN_FRAME_INTERVAL` to 2.

## Test 3: the latency benchmark

This one replays a WAV file to the server exactly like a real client, in real time, 32 ms at a time. Same audio every run, so you can compare settings fairly.

`scripts/fake_client.py`:

```python
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
```

Record yourself saying three things with pauses between them: a wrong number from `facts.md`, a commitment ("Priya will send the deck by Friday"), and a question. Save it as `meeting.wav`.

```bash
uvicorn server.main:app --port 8000
python -m scripts.fake_client meeting.wav
```

Add a screenshot as the second argument to test screen grounding:

```bash
python -m scripts.fake_client meeting.wav slide.jpg
```

What a run looks like (this one is against a mock model I set to answer in 200 ms, to check the plumbing):

```
[speech] {"state": "end", "ms": 5088}
[transcript] {"text": "..."}
[latency] {"ttft_ms": 207}
Revenue was $4.2M, not $5.1M.
[claim] {"claim": "Q3 revenue 5.1M", "verdict": "contradicted", ...}
[speech] {"state": "end", "ms": 3328}
[latency] {"ttft_ms": 202}
[task] {"task": "Send pricing deck", "owner": "Priya", "due": "Friday", ...}

Time to first token after end of speech: [207, 202] ms. Median 204 ms.
```

200 ms of fake model time came out as 202 to 207 ms. The gateway costs you almost nothing. Whatever you see above that against the real API is network plus model.

Run it five times and take the median. One run tells you nothing.

## Test 4: barge-in

Set `BARGE_IN=true`. Ask a long question, and start talking again the moment the first words appear on the HUD. The status line should flip to "interrupted" and the suggestion should clear. In the server log you will see `response.cancel` go out.

## Test 5: the HUD really is hidden

Do this before every important call. Seriously.

1. Start the client. The status should say "hidden from screen share".
2. Open Zoom, Meet or Teams, start a meeting alone, share your whole screen.
3. Look at the preview of what you are sharing. The HUD should not be there.
4. Repeat with OBS or QuickTime screen recording.

If it says "visible to screen share", you are on Linux, on an old Windows build, or on macOS without `pyobjc-framework-Cocoa`.

## A results template for your demo

Copy this into your README after you run the tests:

```
Machine: ________   Network: ________   Model: ________
VAD_SILENCE_MS: ___

VAD cost per frame (median / p95):     ___ / ___ ms
Screen frames sent per minute (talk):   ___
First token after turn end (median):   ___ ms
Felt latency (above + hangover):        ___ ms
Barge-in cancel visible on HUD:         yes / no
Hidden from Zoom / Meet / Teams:        yes / yes / yes
```

Numbers you measured beat numbers from a market report every time.

Next: [07. Draw it in Excalidraw](07-excalidraw.md).
