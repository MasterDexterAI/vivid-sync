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
