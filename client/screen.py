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
