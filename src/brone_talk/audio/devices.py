"""Pemilihan perangkat audio (PortAudio/sounddevice) dan pemetaan kartu PipeWire.

Dipindah dari brone_talk.py (v4) tanpa perubahan logika.
"""

from __future__ import annotations

import sounddevice as sd


def resolve_device(query: str | None, input_device: bool) -> int | None:
    """Resolve an explicit index/name, otherwise prefer the reSpeaker XVF3800."""
    if not query or query.lower() in {"default", "none"}:
        if not input_device:
            return None
        query = "reSpeaker XVF3800"

    if query.isdigit():
        return int(query)

    wanted = query.lower()
    devices = sd.query_devices()
    channel_key = "max_input_channels" if input_device else "max_output_channels"
    for index, device in enumerate(devices):
        if device.get(channel_key, 0) > 0 and wanted in device["name"].lower():
            return index
    raise RuntimeError(f"Device audio tidak ditemukan: {query}")

def device_name(device: int | None) -> str:
    if device is None:
        return "default"
    return str(sd.query_devices(device)["name"])

def parse_card_nodes(spec: str) -> list[tuple[str, str]]:
    """Ubah "kartu=node,kartu=node" (mis. "XVF3800=brone-mic-xvf") jadi [(kartu, node), ...]."""
    pairs = []
    for item in spec.split(","):
        card, _, node = item.partition("=")
        if card.strip() and node.strip():
            pairs.append((card.strip(), node.strip()))
    return pairs
