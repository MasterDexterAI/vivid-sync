# 04. The server: FastAPI gateway, Silero VAD, OpenAI Realtime

The server sits between your laptop and OpenAI. It does four things:

1. Takes raw audio from the client and decides when a turn starts and ends.
2. Keeps the newest screenshot and slips it in right before each turn.
3. Holds the OpenAI Realtime socket and drives it with explicit events.
4. Turns model output and tool calls into small events the HUD can draw.

Why a gateway at all, when OpenAI supports direct WebRTC from the client? Because your API key never touches the laptop, your VAD decides turns, and silence never gets billed. That last one is real money on hour-long calls.

## The flow of one turn

```
client audio (24 kHz, 32 ms frames)
   │
   ▼
Silero VAD ──► speech_start ──► cancel running answer, flush 320 ms preroll
   │                             stream frames to OpenAI while speaking
   ▼
speech_end ──► send newest screenshot (if it changed)
           ──► input_audio_buffer.commit
           ──► response.create (text only)
   │
   ▼
OpenAI streams text deltas and function calls back
   │
   ▼
HUD gets: latency, delta, claim, task, done
```

## config.py

```python
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
```

Every setting has a default, so the server boots with only `OPENAI_API_KEY` set. `frozen=True` means nothing mutates settings at runtime by accident.

## vad.py

```python
import numpy as np
import onnxruntime as ort
from scipy.signal import resample_poly

VAD_RATE = 16000
VAD_FRAME = 512
CONTEXT = 64
FRAME_MS = 32
INPUT_RATE = 24000
INPUT_FRAME = 768
INPUT_FRAME_BYTES = INPUT_FRAME * 2


class SileroVAD:
    def __init__(self, model_path: str):
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
        self.sr = np.array(VAD_RATE, dtype=np.int64)
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, CONTEXT), dtype=np.float32)

    def probability(self, frame_16k: np.ndarray) -> float:
        x = np.concatenate([self.context, frame_16k.reshape(1, -1).astype(np.float32)], axis=1)
        out, self.state = self.session.run(None, {"input": x, "state": self.state, "sr": self.sr})
        self.context = x[:, -CONTEXT:]
        return float(out[0][0])


def pcm24k_to_vad_frame(pcm16_24k: bytes) -> np.ndarray:
    x = np.frombuffer(pcm16_24k, dtype=np.int16).astype(np.float32) / 32768.0
    return resample_poly(x, 2, 3).astype(np.float32)


class TurnDetector:
    def __init__(self, vad: SileroVAD, start: float = 0.5, end: float = 0.35, silence_ms: int = 350, onset_frames: int = 2):
        self.vad = vad
        self.start = start
        self.end = end
        self.silence_ms = silence_ms
        self.onset_frames = onset_frames
        self.speaking = False
        self.above = 0
        self.silent_ms = 0
        self.speech_ms = 0
        self.last_prob = 0.0

    def feed(self, pcm16_24k: bytes) -> str | None:
        p = self.vad.probability(pcm24k_to_vad_frame(pcm16_24k))
        self.last_prob = p
        if not self.speaking:
            self.above = self.above + 1 if p >= self.start else 0
            if self.above >= self.onset_frames:
                self.speaking = True
                self.silent_ms = 0
                self.speech_ms = self.above * FRAME_MS
                return "speech_start"
            return None
        self.speech_ms += FRAME_MS
        if p < self.end:
            self.silent_ms += FRAME_MS
            if self.silent_ms >= self.silence_ms:
                self.speaking = False
                self.above = 0
                return "speech_end"
        else:
            self.silent_ms = 0
        return None
```

Three things worth knowing here.

**The context window.** Silero v5 does not take 512 samples. It takes 576: the last 64 samples of the previous frame glued to the front of the new one. Skip that and the probabilities come out wrong without any error. The official wrapper does this and so does ours.

**The resample.** OpenAI wants 24 kHz. Silero wants 16 kHz. So the client sends 24 kHz in 768-sample frames (32 ms), the exact audio goes to OpenAI untouched, and a copy gets resampled 3:2 down to 512 samples just for the VAD. The model hears clean audio. The VAD hears good-enough audio.

**Hysteresis.** Speech starts when probability crosses 0.5 for two frames in a row. It ends only when probability stays under 0.35 for 350 ms. Two thresholds, not one, so a breath in the middle of a sentence does not end the turn.

On my run, a 13-second clip with two sentences produced exactly two start events and two end events. Median VAD cost: 0.71 ms per frame. p95: 1.12 ms. The frame itself is 32 ms long, so the VAD uses about 2% of real time on one CPU core.

## prompts.py

```python
from pathlib import Path

BASE = """You are Vivid Sync, a silent meeting co-pilot. You never speak to the meeting. You write to one person: the user, on a small overlay.

You receive the meeting audio turn by turn. Sometimes a screenshot of the user's screen arrives right before a turn. Treat it as what everyone is looking at right now.

Rules:
1. If someone commits to doing something, call add_task. One call per commitment.
2. If a number, date or factual claim is said aloud or shown on screen, check it against KNOWLEDGE and the screenshot. Call flag_claim only when the verdict is contradicted, or when the claim matters and you cannot verify it.
3. If a question is aimed at the user, write the answer they could say, in under 25 words.
4. If none of that applies, reply with exactly: PASS
5. Never repeat the transcript. Never explain yourself. No greetings.

KNOWLEDGE:
{knowledge}
"""


def build_instructions(knowledge_path: str) -> str:
    path = Path(knowledge_path)
    knowledge = path.read_text(encoding="utf-8") if path.exists() else "(empty)"
    return BASE.format(knowledge=knowledge[:20000])
```

The `PASS` rule is the most important line in the prompt. Without it, the model comments on every single sentence and your HUD turns into noise. With it, the model stays quiet unless it has a task, a contradiction, or an answer. The server swallows `PASS` before it ever reaches the screen.

The knowledge file is pasted straight into the instructions. For a few pages of facts, that is faster than any retrieval call. When your facts grow past 20 KB, move to a `lookup_facts` tool backed by a vector store. Not before.

## tools.py

```python
import json
import time

TOOLS = [
    {
        "type": "function",
        "name": "add_task",
        "description": "Record an action item the moment someone commits to doing something.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What needs to happen, starting with a verb."},
                "owner": {"type": "string", "description": "Who owns it. Use 'unassigned' if nobody was named."},
                "due": {"type": "string", "description": "Deadline as spoken, or 'none'."},
            },
            "required": ["task", "owner", "due"],
        },
    },
    {
        "type": "function",
        "name": "flag_claim",
        "description": "Fact-check a specific number, date or factual claim that was said aloud or is visible on screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "The claim, quoted as closely as possible."},
                "verdict": {"type": "string", "enum": ["supported", "contradicted", "unverifiable"]},
                "evidence": {"type": "string", "description": "One line: the fact from the knowledge file or screen that decides it."},
                "source": {"type": "string", "enum": ["speech", "screen", "both"]},
            },
            "required": ["claim", "verdict", "evidence", "source"],
        },
    },
]


def handle_tool_call(name: str, arguments: str) -> tuple[dict | None, dict]:
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return None, {"ok": False, "error": "bad json"}
    if name == "add_task":
        event = {"type": "task", "task": args.get("task", ""), "owner": args.get("owner", "unassigned"), "due": args.get("due", "none"), "at": time.time()}
        return event, {"ok": True}
    if name == "flag_claim":
        event = {"type": "claim", "claim": args.get("claim", ""), "verdict": args.get("verdict", "unverifiable"), "evidence": args.get("evidence", ""), "source": args.get("source", "speech"), "at": time.time()}
        return event, {"ok": True}
    return None, {"ok": False, "error": f"unknown tool {name}"}
```

Two tools. That is enough for the demo and enough to prove the pattern. The model fills in structured arguments, the server turns them into HUD events, and a `function_call_output` goes back so the conversation stays valid. No second `response.create` after the tool call, because the co-pilot has nothing more to say.

Adding a third tool, like `push_to_linear`, is one dictionary in `TOOLS` and one `if` branch in `handle_tool_call`.

## session.py

```python
import asyncio
import base64
import json
import time
from collections import deque

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from .config import settings
from .prompts import build_instructions
from .tools import TOOLS, handle_tool_call
from .vad import INPUT_FRAME_BYTES, SileroVAD, TurnDetector

PREROLL_FRAMES = 10


class CopilotSession:
    def __init__(self, client: WebSocket):
        self.client = client
        self.openai = None
        self.turns = TurnDetector(SileroVAD(settings.vad_model_path), settings.vad_start, settings.vad_end, settings.vad_silence_ms)
        self.preroll = deque(maxlen=PREROLL_FRAMES)
        self.pending = b""
        self.latest_frame = None
        self.latest_frame_id = 0
        self.sent_frame_id = 0
        self.response_active = False
        self.queued_response = False
        self.turn_ended_at = None
        self.first_token_seen = False
        self.text_buffer = ""
        self.text_released = False

    async def connect(self):
        url = f"{settings.realtime_url}?model={settings.realtime_model}"
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        self.openai = await websockets.connect(url, additional_headers=headers, max_size=None, ping_interval=20)
        await self.send_openai({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": settings.realtime_model,
                "output_modalities": ["text"],
                "instructions": build_instructions(settings.knowledge_path),
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "turn_detection": None,
                        "transcription": {"model": settings.transcribe_model},
                    }
                },
                "tools": TOOLS,
                "tool_choice": "auto",
            },
        })

    async def run(self):
        try:
            await self.connect()
        except Exception as exc:
            await self.send_client({"type": "error", "message": f"could not reach OpenAI: {exc}"})
            return
        await self.send_client({"type": "status", "state": "ready", "model": settings.realtime_model})
        tasks = [asyncio.create_task(self.pump_client()), asyncio.create_task(self.pump_openai())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

    async def close(self):
        if self.openai is not None:
            await self.openai.close()

    async def send_openai(self, event: dict):
        await self.openai.send(json.dumps(event))

    async def send_client(self, event: dict):
        try:
            await self.client.send_text(json.dumps(event))
        except (RuntimeError, WebSocketDisconnect):
            pass

    async def pump_client(self):
        try:
            while True:
                msg = await self.client.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes") is not None:
                    await self.on_audio(msg["bytes"])
                elif msg.get("text") is not None:
                    await self.on_control(json.loads(msg["text"]))
        except WebSocketDisconnect:
            return

    async def on_control(self, event: dict):
        if event.get("type") == "frame":
            self.latest_frame = event["jpeg"]
            self.latest_frame_id += 1
        elif event.get("type") == "ping":
            await self.send_client({"type": "pong", "t": event.get("t")})

    async def on_audio(self, chunk: bytes):
        data = self.pending + chunk
        usable = len(data) - len(data) % INPUT_FRAME_BYTES
        self.pending = data[usable:]
        for i in range(0, usable, INPUT_FRAME_BYTES):
            frame = data[i:i + INPUT_FRAME_BYTES]
            event = self.turns.feed(frame)
            if event == "speech_start":
                await self.on_speech_start()
            if self.turns.speaking:
                await self.append_audio(frame)
            else:
                self.preroll.append(frame)
            if event == "speech_end":
                await self.on_speech_end()

    async def append_audio(self, frame: bytes):
        await self.send_openai({"type": "input_audio_buffer.append", "audio": base64.b64encode(frame).decode("ascii")})

    async def on_speech_start(self):
        if self.response_active and settings.barge_in:
            await self.send_openai({"type": "response.cancel"})
            await self.send_client({"type": "interrupted"})
        for frame in self.preroll:
            await self.append_audio(frame)
        self.preroll.clear()
        await self.send_client({"type": "speech", "state": "start"})

    async def on_speech_end(self):
        await self.send_client({"type": "speech", "state": "end", "ms": self.turns.speech_ms})
        if self.latest_frame and self.latest_frame_id != self.sent_frame_id:
            await self.send_openai({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "[SCREEN] This is the user's screen at the end of the next turn."},
                        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{self.latest_frame}"},
                    ],
                },
            })
            self.sent_frame_id = self.latest_frame_id
        await self.send_openai({"type": "input_audio_buffer.commit"})
        if self.turns.speech_ms < settings.min_turn_ms:
            return
        self.turn_ended_at = time.perf_counter()
        self.first_token_seen = False
        if self.response_active:
            self.queued_response = True
        else:
            await self.create_response()

    async def create_response(self):
        self.queued_response = False
        self.response_active = True
        self.text_buffer = ""
        self.text_released = False
        await self.send_openai({"type": "response.create", "response": {"output_modalities": ["text"]}})

    def mark_first_token(self):
        if self.first_token_seen or self.turn_ended_at is None:
            return None
        self.first_token_seen = True
        return round((time.perf_counter() - self.turn_ended_at) * 1000)

    async def pump_openai(self):
        try:
            async for raw in self.openai:
                await self.on_openai_event(json.loads(raw))
        except websockets.ConnectionClosed as exc:
            await self.send_client({"type": "error", "message": f"upstream closed: {exc.code}"})

    async def on_openai_event(self, ev: dict):
        kind = ev.get("type", "")
        if kind == "response.created":
            self.response_active = True
        elif kind in ("response.output_text.delta", "response.function_call_arguments.delta"):
            ms = self.mark_first_token()
            if ms is not None:
                await self.send_client({"type": "latency", "ttft_ms": ms})
            if kind == "response.output_text.delta":
                await self.on_text_delta(ev.get("delta", ""))
        elif kind == "response.done":
            await self.on_response_done(ev.get("response", {}))
        elif kind == "conversation.item.input_audio_transcription.completed":
            await self.send_client({"type": "transcript", "text": ev.get("transcript", "")})
        elif kind == "error":
            await self.send_client({"type": "error", "message": ev.get("error", {}).get("message", str(ev))})

    async def on_text_delta(self, delta: str):
        self.text_buffer += delta
        if self.text_released:
            await self.send_client({"type": "delta", "text": delta})
            return
        if "PASS".startswith(self.text_buffer.strip()):
            return
        self.text_released = True
        await self.send_client({"type": "delta", "text": self.text_buffer})

    async def on_response_done(self, response: dict):
        self.response_active = False
        for item in response.get("output", []):
            if item.get("type") != "function_call":
                continue
            client_event, output = handle_tool_call(item.get("name", ""), item.get("arguments", "{}"))
            if client_event:
                await self.send_client(client_event)
            await self.send_openai({
                "type": "conversation.item.create",
                "item": {"type": "function_call_output", "call_id": item.get("call_id"), "output": json.dumps(output)},
            })
        if self.text_released:
            await self.send_client({"type": "done", "status": response.get("status")})
        if self.queued_response:
            await self.create_response()
```

The parts that matter:

**`connect()`** sends one `session.update`: text output only, 24 kHz PCM input, `turn_detection: None` so OpenAI's VAD stays out of the way, input transcription on so the HUD can show what was heard, and the two tools.

**`on_audio()`** cuts incoming bytes into exact 32 ms frames, even if the network delivers them in odd sizes. Each frame goes through the VAD. While someone speaks, frames stream to OpenAI with `input_audio_buffer.append`. While nobody speaks, frames sit in a 10-frame ring buffer, the preroll.

**The preroll.** VAD needs two frames above threshold before it says "speech". By then you have already lost the first 64 ms of the word, plosives included. So on `speech_start`, the last 320 ms of audio gets flushed to OpenAI first. "Paris" stays "Paris" and does not become "aris".

**`on_speech_start()`** is barge-in. If a response is still running, `response.cancel` goes out and the HUD clears. There is no `conversation.item.truncate` here, and that is on purpose. Truncate exists to cut model audio the user did not hear. This co-pilot never produces audio, so there is nothing to truncate.

**`on_speech_end()`** sends the screenshot, then commits the audio, then asks for a response. That order means the image sits in the conversation just before the audio it belongs to. When someone says "that number on the slide is wrong", the slide is already there.

**`queued_response`.** If a new turn ends while the old response is still being cancelled, OpenAI rejects a second `response.create`. So the server queues it and fires it on `response.done`. You will hit this race the moment the model is slower than the pause between two speakers.

**Latency.** `turn_ended_at` is stamped the instant the VAD fires `speech_end`. The first text delta or function argument delta stops the clock. That number goes to the HUD as `ttft_ms`.

## main.py

```python
from fastapi import FastAPI, WebSocket

from .config import settings
from .session import CopilotSession

app = FastAPI(title="Vivid Sync")


@app.get("/health")
async def health():
    return {"ok": True, "model": settings.realtime_model, "key_loaded": bool(settings.openai_api_key)}


@app.websocket("/ws")
async def copilot_socket(ws: WebSocket):
    await ws.accept()
    session = CopilotSession(ws)
    try:
        await session.run()
    finally:
        await session.close()
```

## Run it

```bash
uvicorn server.main:app --port 8000
```

In another terminal:

```bash
curl http://127.0.0.1:8000/health
```

You want `"key_loaded": true`. If it says false, your `.env` is not where the server expects it (the project root).

Next: [05. The client](05-client.md).
