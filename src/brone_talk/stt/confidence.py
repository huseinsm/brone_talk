"""Skor confidence STT dari segmen faster-whisper. Dipindah dari brone_v4.py."""

from __future__ import annotations

import math


def stt_confidence_from_segments(segments: list) -> dict[str, float]:
    """Skor confidence STT dari segmen faster-whisper, TANPA mengubah proses transkripsi.

    avg_logprob adalah rata-rata log-probabilitas token; exp() mengubahnya ke skala 0..1.
    stt_mean_prob: rata-rata tertimbang panjang segmen; stt_min_prob: segmen terlemah.
    """
    segs = [s for s in segments if getattr(s, "text", "").strip()]
    if not segs:
        return {"stt_mean_prob": 0.0, "stt_min_prob": 0.0}
    weights = [max(1, len(s.text.split())) for s in segs]
    mean_lp = sum(w * s.avg_logprob for w, s in zip(weights, segs)) / sum(weights)
    return {"stt_mean_prob": round(math.exp(mean_lp), 4),
            "stt_min_prob": round(math.exp(min(s.avg_logprob for s in segs)), 4)}
