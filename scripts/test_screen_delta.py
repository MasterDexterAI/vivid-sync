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
