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
