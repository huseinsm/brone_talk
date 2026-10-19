"""llm: bagian mesin jawaban v4 (dipindah dari brone_v4.py tanpa perubahan logika)."""

from __future__ import annotations

import json
import re
import time


from brone_talk.engine.util import _http_json

SYSTEM_PROMPT = """Kamu adalah Bron, robot humanoid maskot Universitas Brawijaya. Kamu menjawab pengunjung dengan suara dalam bahasa Indonesia.

Balas HANYA dengan JSON valid tanpa markdown:
{"answerable": true, "response": "jawaban", "expression": "happy|neutral|sad|excited|confused"}

Aturan:
1. Jawab HANYA dengan fakta yang tertulis di KONTEKS. Jangan menambah nama, angka, tanggal, atau fakta lain.
2. Jika KONTEKS tidak memuat jawabannya, balas {"answerable": false, "response": "", "expression": "neutral"}.
3. Jawaban maksimal 40 kata, langsung ke inti.
4. Jawaban akan diucapkan: tulis kata lengkap (Jalan, Nomor, Profesor, Doktor), bukan singkatan.
5. Nomor telepon, kode pos, dan nomor surat disalin persis seperti di KONTEKS."""

class LLMBackend:
    def __init__(self, name: str, url: str, model: str, api_key: str, timeout_s: float, max_tokens: int,
                 extra: dict | None = None) -> None:
        self.name, self.url, self.model, self.api_key = name, url, model, api_key
        self.timeout_s, self.max_tokens, self.extra = timeout_s, max_tokens, extra or {}

    def chat(self, messages: list[dict]) -> tuple[str, dict]:
        body = {"model": self.model, "messages": messages, "stream": False, "temperature": 0.1,
                "max_tokens": self.max_tokens, "response_format": {"type": "json_object"}, **self.extra}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        t0 = time.perf_counter()
        res = _http_json(self.url, body, timeout=self.timeout_s, headers=headers)
        choice = (res.get("choices") or [{}])[0]
        usage = res.get("usage") or {}
        return str(choice.get("message", {}).get("content", "")), {
            "ms": round((time.perf_counter() - t0) * 1000), "prompt_tokens": usage.get("prompt_tokens"),
            "gen_tokens": usage.get("completion_tokens")}

def parse_llm_json(raw: str) -> dict | None:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
