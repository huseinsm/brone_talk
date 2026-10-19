"""Silero VAD (ONNX) untuk deteksi ucapan per jendela 32 ms. Dipindah dari brone_talk.py (v4)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort

from brone_talk.audio.constants import SAMPLE_RATE, VAD_CONTEXT, VAD_STATE_SHAPE, VAD_WINDOW


class SileroVad:
    """ONNX streaming wrapper matching Silero's 16 kHz context requirement."""

    def __init__(self, model_path: Path) -> None:
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"], sess_options=options
        )
        self.reset()

    def reset(self) -> None:
        self.state = np.zeros(VAD_STATE_SHAPE, dtype=np.float32)
        self.context = np.zeros((1, VAD_CONTEXT), dtype=np.float32)

    def probability(self, samples: np.ndarray) -> float:
        window = np.asarray(samples, dtype=np.float32).reshape(1, -1)
        if window.shape[1] < VAD_WINDOW:
            window = np.pad(window, ((0, 0), (0, VAD_WINDOW - window.shape[1])))
        elif window.shape[1] > VAD_WINDOW:
            window = window[:, :VAD_WINDOW]
        inputs = np.concatenate([self.context, window], axis=1)
        output, self.state = self.session.run(
            None,
            {"input": inputs, "state": self.state, "sr": np.array(SAMPLE_RATE, dtype=np.int64)},
        )
        self.context = window[:, -VAD_CONTEXT:]
        return float(output[0][0])
