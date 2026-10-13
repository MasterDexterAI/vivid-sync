# 05. The client: ears, eyes and a face nobody else sees

The client is dumb on purpose. It captures, filters, ships, and draws. All the decisions live on the server, so you can change behavior without reinstalling anything on your laptop.

Two threads matter:

- The Qt main thread draws the HUD. Qt insists on this.
- A background thread runs an asyncio loop with three tasks: send audio, send screen frames, receive events.

They talk through one Qt signal. Never touch a widget from the network thread. Qt will crash in a way that takes an afternoon to trace.

## config.py

```python
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
```

## audio.py

```python
import asyncio

import sounddevice as sd

RATE = 24000
BLOCK = 768


class AudioStreamer:
    def __init__(self, device: int | None = None):
        self.device = device

    async def chunks(self):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)

        def push(data: bytes):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(data)

        def callback(indata, frames, time_info, status):
            loop.call_soon_threadsafe(push, bytes(indata))

        with sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16", device=self.device, callback=callback):
            while True:
                yield await queue.get()
```

24 kHz, mono, 16-bit, 768 samples per block. That is 32 ms per callback, which lines up exactly with one VAD frame on the server.

The callback runs on a PortAudio thread, so it hands bytes to asyncio with `call_soon_threadsafe`. If the network stalls, the queue drops the oldest audio instead of growing forever. Stale audio is useless to a live co-pilot. Better to lose 3 seconds than to answer 3 seconds late.

## screen.py

```python
import asyncio
import threading
import time

import cv2
import mss
import numpy as np

TARGET_WIDTH = 1280


class ScreenDeltaDetector:
    def __init__(self, threshold_ratio: float = 0.015, min_interval_sec: float = 1.0, jpeg_quality: int = 75):
        self.threshold_ratio = threshold_ratio
        self.min_interval_sec = min_interval_sec
        self.jpeg_quality = jpeg_quality
        self.last_gray = None
        self.last_sent = 0.0
        self.last_ratio = 0.0

    def resize(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= TARGET_WIDTH:
            return frame
        scale = TARGET_WIDTH / w
        return cv2.resize(frame, (TARGET_WIDTH, int(h * scale)), interpolation=cv2.INTER_AREA)

    def encode(self, frame: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        return buf.tobytes() if ok else b""

    def evaluate(self, bgr: np.ndarray, now: float) -> bytes | None:
        small = self.resize(bgr)
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (21, 21), 0)
        if self.last_gray is None or self.last_gray.shape != gray.shape:
            self.last_gray = gray
            self.last_sent = now
            return self.encode(small)
        diff = cv2.absdiff(self.last_gray, gray)
        _, mask = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        self.last_ratio = np.count_nonzero(mask) / mask.size
        if self.last_ratio > self.threshold_ratio and now - self.last_sent >= self.min_interval_sec:
            self.last_gray = gray
            self.last_sent = now
            return self.encode(small)
        return None


class ScreenSampler:
    def __init__(self, monitor: int = 1, hz: float = 2.0, detector: ScreenDeltaDetector | None = None):
        self.monitor = monitor
        self.period = 1.0 / hz
        self.detector = detector or ScreenDeltaDetector()
        self.stats = {"captured": 0, "sent": 0}

    def _capture_loop(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, stop: threading.Event):
        with mss.mss() as sct:
            area = sct.monitors[self.monitor]
            while not stop.is_set():
                started = time.perf_counter()
                bgr = np.asarray(sct.grab(area))[:, :, :3]
                self.stats["captured"] += 1
                jpeg = self.detector.evaluate(bgr, time.time())
                if jpeg:
                    self.stats["sent"] += 1
                    loop.call_soon_threadsafe(queue.put_nowait, jpeg)
                stop.wait(max(0.0, self.period - (time.perf_counter() - started)))

    async def frames(self):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        stop = threading.Event()
        worker = threading.Thread(target=self._capture_loop, args=(loop, queue, stop), daemon=True)
        worker.start()
        try:
            while True:
                yield await queue.get()
        finally:
            stop.set()
```

This is where the money is saved.

The capture thread grabs the screen twice a second. Each frame is shrunk to 1280 px wide, turned gray, and blurred with a 21 px Gaussian kernel. The blur is what makes a blinking cursor and font anti-aliasing invisible to the diff. Then it counts how many pixels changed by more than 25 brightness levels. Over 1.5% of the screen, and at least a second since the last send? Ship it as a JPEG.

What I saw on a synthetic 4K test with 30 captures:

- 10 identical frames of a slide: 1 sent (the first one).
- 10 frames with a cursor-sized change: 0 sent.
- 10 frames of a new slide: 1 sent. Delta was 0.325.
- JPEGs came out at 14 to 18 KB. The filter itself took about 18 ms per 4K frame.

2 frames out of 30. And the server goes one step further: it only forwards the newest frame, and only when a turn ends. If you flip through five slides while nobody talks, OpenAI sees one image, the one on screen when someone actually says something about it.

> Sending video to an LLM is like recording a whole lecture to catch one sentence. Send the slide when someone talks about the slide.

## stealth.py

```python
import sys

WDA_EXCLUDEFROMCAPTURE = 0x00000011


def hide_from_capture(win_id: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        return bool(user32.SetWindowDisplayAffinity(wintypes.HWND(win_id), WDA_EXCLUDEFROMCAPTURE))
    if sys.platform == "darwin":
        try:
            import objc
            from AppKit import NSWindowSharingNone
        except ImportError:
            return False
        view = objc.objc_object(c_void_p=win_id)
        window = view.window()
        if window is None:
            return False
        window.setSharingType_(NSWindowSharingNone)
        return True
    return False
```

This is the "nobody else sees it" part. Both operating systems let a window opt out of screen capture at the compositor level. The window still draws on your monitor. Zoom, Meet, Teams and OBS get nothing where it sits.

- Windows 10 2004 and newer: `SetWindowDisplayAffinity` with `WDA_EXCLUDEFROMCAPTURE`.
- macOS: `NSWindow.setSharingType_(NSWindowSharingNone)`. Qt gives you an `NSView` pointer, so you go view, then window.

There is a nice side effect. The client's own `mss` capture also cannot see the HUD. So the co-pilot never reads its own suggestions back off the screen and starts commenting on them. Without this flag you get a feedback loop.

Two warnings, and I mean them. OS updates have changed this behavior before, especially on macOS with ScreenCaptureKit. Test it on every machine, with every app you share from, before you trust it in a call that matters. Step 06 has the test.

And use it for what it is good for: keeping private notes and numbers off a shared screen. Using it to pass someone else's assessment as your own work is cheating, and interview platforms are getting good at catching it.

## hud.py

```python
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

STYLE = """
QWidget#panel { background: rgba(18, 18, 20, 225); border-radius: 12px; }
QLabel { color: #e8e8e8; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 13px; }
QLabel#status { color: #9aa0a6; font-size: 11px; }
QLabel#header { color: #9aa0a6; font-size: 10px; letter-spacing: 1px; }
QLabel#answer { font-size: 15px; color: #ffffff; }
QListWidget { background: transparent; border: none; color: #e8e8e8; font-size: 12px; }
"""

VERDICT_COLORS = {"contradicted": "#ff6b6b", "unverifiable": "#f5c542", "supported": "#7bd88f"}


class Bridge(QObject):
    event = Signal(dict)


class Hud(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vivid Sync")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(420, 560)
        self.drag_from = None

        panel = QWidget(self)
        panel.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)

        self.status = QLabel("connecting")
        self.status.setObjectName("status")
        self.answer = QLabel("")
        self.answer.setObjectName("answer")
        self.answer.setWordWrap(True)
        self.transcript = QLabel("")
        self.transcript.setWordWrap(True)
        self.transcript.setStyleSheet("color:#8a8f98; font-size:11px;")
        self.claims = QListWidget()
        self.tasks = QListWidget()

        for title, widget in (("STATUS", self.status), ("SUGGESTION", self.answer), ("HEARD", self.transcript), ("FACT CHECKS", self.claims), ("TASKS", self.tasks)):
            header = QLabel(title)
            header.setObjectName("header")
            layout.addWidget(header)
            layout.addWidget(widget)
        self.setStyleSheet(STYLE)
        self.latency = None
        self.speaking = False

    def mousePressEvent(self, e):
        self.drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag_from is not None:
            self.move(e.globalPosition().toPoint() - self.drag_from)

    def mouseReleaseEvent(self, e):
        self.drag_from = None

    def refresh_status(self, state: str):
        parts = [state]
        if self.latency is not None:
            parts.append(f"first token {self.latency} ms")
        self.status.setText("  ·  ".join(parts))

    def on_event(self, ev: dict):
        kind = ev.get("type")
        if kind == "status":
            self.refresh_status(f"ready · {ev.get('model', '')}")
        elif kind == "speech":
            self.refresh_status("listening" if ev["state"] == "start" else "thinking")
        elif kind == "latency":
            self.latency = ev["ttft_ms"]
            self.refresh_status("answering")
        elif kind == "delta":
            if self.answer.property("fresh"):
                self.answer.setText("")
                self.answer.setProperty("fresh", False)
            self.answer.setText(self.answer.text() + ev["text"])
        elif kind == "done":
            self.answer.setProperty("fresh", True)
        elif kind == "interrupted":
            self.answer.setProperty("fresh", True)
            self.refresh_status("interrupted")
        elif kind == "transcript":
            self.transcript.setText(ev["text"][-240:])
        elif kind == "claim":
            item = QListWidgetItem(f"{ev['verdict'].upper()}  {ev['claim']}\n  {ev['evidence']}")
            item.setForeground(QColor(VERDICT_COLORS.get(ev["verdict"], "#e8e8e8")))
            self.claims.insertItem(0, item)
        elif kind == "task":
            self.tasks.addItem(f"☐ {ev['task']}  ({ev['owner']}, {ev['due']})")
        elif kind == "error":
            self.refresh_status(f"error: {ev.get('message', '')[:80]}")
        elif kind == "connection":
            self.refresh_status(ev["state"])
```

Frameless, always on top, translucent dark panel, draggable anywhere. `Qt.Tool` keeps it out of the taskbar and the Alt+Tab list.

Five zones, top to bottom:

- Status: ready, listening, thinking, answering, plus the last first-token latency.
- Suggestion: what to say, streamed word by word. Cleared on the next answer or on barge-in.
- Heard: the last 240 characters of transcript, so you can see the co-pilot is actually following.
- Fact checks: newest first, colored red for contradicted, amber for unverifiable, green for supported.
- Tasks: one line per commitment, with owner and due date.

## main.py

```python
import asyncio
import base64
import json
import sys
import threading

import websockets
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .audio import AudioStreamer
from .config import settings
from .hud import Bridge, Hud
from .screen import ScreenDeltaDetector, ScreenSampler
from .stealth import hide_from_capture


async def stream_session(bridge: Bridge):
    async with websockets.connect(settings.server_url, max_size=None, ping_interval=20) as ws:
        bridge.event.emit({"type": "connection", "state": "connected"})
        audio = AudioStreamer(settings.audio_device)
        detector = ScreenDeltaDetector(settings.delta_threshold, settings.min_frame_interval, settings.jpeg_quality)
        screen = ScreenSampler(settings.monitor, settings.screen_hz, detector)

        async def send_audio():
            async for chunk in audio.chunks():
                await ws.send(chunk)

        async def send_screen():
            async for jpeg in screen.frames():
                await ws.send(json.dumps({"type": "frame", "jpeg": base64.b64encode(jpeg).decode("ascii")}))

        async def receive():
            async for raw in ws:
                bridge.event.emit(json.loads(raw))

        await asyncio.gather(send_audio(), send_screen(), receive())


async def run_forever(bridge: Bridge):
    delay = 1
    while True:
        try:
            await stream_session(bridge)
            delay = 1
        except Exception as exc:
            bridge.event.emit({"type": "connection", "state": f"reconnecting in {delay}s ({type(exc).__name__})"})
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)


def main():
    app = QApplication(sys.argv)
    hud = Hud()
    bridge = Bridge()
    bridge.event.connect(hud.on_event)
    screen_geo = app.primaryScreen().availableGeometry()
    hud.move(screen_geo.right() - hud.width() - 24, screen_geo.top() + 80)
    hud.show()
    if settings.hide_from_capture:
        QTimer.singleShot(200, lambda: hud.status.setText("hidden from screen share" if hide_from_capture(int(hud.winId())) else "visible to screen share"))
    threading.Thread(target=lambda: asyncio.run(run_forever(bridge)), daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

The reconnect loop doubles its wait from 1 to 15 seconds. Restart the server mid-call and the HUD says "reconnecting", then picks back up. The stealth flag is applied 200 ms after the window shows, because the native window handle does not exist before the first paint on some platforms.

## Run it

Server in one terminal, client in another:

```bash
uvicorn server.main:app --port 8000
```

```bash
python -m client.main
```

Or pick "Server + Client" in the VS Code Run and Debug panel and hit F5.

First run on macOS will ask for two permissions: Microphone and Screen Recording. Grant both to your terminal app (or to VS Code if you launched from there), then restart the client. Screen Recording permission does not apply until the app restarts.

Say "Our Q3 revenue was five point one million." The HUD should flag it as contradicted, because `facts.md` says $4.2M.

Next: [06. Run it and measure it](06-run-and-measure.md).
