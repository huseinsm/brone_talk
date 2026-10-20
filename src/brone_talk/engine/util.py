"""Utilitas bersama mesin jawaban: normalisasi teks, HTTP JSON, dan tunggu server siap.

Helper env ada di config.py.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any


LOG = logging.getLogger("brone-talk.v4")


def norm_text(text: str) -> str:
    """Huruf kecil, tanpa tanda baca. Harus sama dengan kb/build_kb.py:norm_text."""
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z]+", " ", str(text).lower())).strip()

def _http_json(url: str, body: dict | None, timeout: float, headers: dict | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})},
                                 method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def wait_for_server(base_url: str, timeout_s: float) -> bool:
    """Tunggu llama-server siap (/health 200) maksimal timeout_s detik."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            _http_json(base_url.rstrip("/") + "/health", None, timeout=3)
            return True
        except Exception:
            if time.monotonic() > deadline:
                return False
            time.sleep(1)
