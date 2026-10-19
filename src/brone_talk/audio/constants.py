"""Konstanta audio: 16 kHz mono, jendela VAD 512 sampel (32 ms), konteks Silero 64 sampel."""

SAMPLE_RATE = 16_000
VAD_WINDOW = 512
VAD_CONTEXT = 64
VAD_STATE_SHAPE = (2, 1, 128)
