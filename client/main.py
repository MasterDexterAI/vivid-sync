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
