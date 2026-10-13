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
