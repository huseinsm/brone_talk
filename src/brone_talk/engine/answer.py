"""answer: bagian mesin jawaban v4 (dipindah dari brone_v4.py tanpa perubahan logika)."""

from __future__ import annotations

import datetime as _dt
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


from brone_talk.engine.util import _env, _env_f, _env_i, norm_text, wait_for_server
from brone_talk.engine.servers import Embedder, Reranker
from brone_talk.engine.entities import EntityMatcher
from brone_talk.engine.faq import FaqIndex
from brone_talk.engine.retrieval import HybridRetriever
from brone_talk.engine.llm import LLMBackend, SYSTEM_PROMPT, parse_llm_json
from brone_talk.engine.grounding import grounding_problems
from brone_talk.messages import MSG_MOTION, MSG_NOT_UNDERSTOOD, MSG_NO_INFO, MSG_SERVICE_DOWN
from brone_talk.engine.util import LOG

_MOTION_RE = re.compile(r"\b(me)?(lambai\w*|lambaikan|duduk|berdiri|jalan\w*|ikut\w*|wave|sit|stand|follow)\b", re.I)

_MOTION_QUESTION_RE = re.compile(r"\b(bisa|dapat|mampu|apakah|kah)\b", re.I)

@dataclass
class EngineConfig:
    kb_dir: Path
    runtime_dir: Path
    embed_url: str = field(default_factory=lambda: _env("BRONE_EMBED_URL", "http://127.0.0.1:8082"))
    rerank_url: str = field(default_factory=lambda: _env("BRONE_RERANK_URL", "http://127.0.0.1:8083"))
    local_url: str = field(default_factory=lambda: _env("BRONE_LOCAL_URL", "http://127.0.0.1:8081"))
    local_model: str = field(default_factory=lambda: _env("BRONE_LOCAL_MODEL", "lfm2.5-2.6b"))
    cloud_url: str = field(default_factory=lambda: _env("BRONE_DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"))
    cloud_model: str = field(default_factory=lambda: _env("BRONE_DEEPSEEK_MODEL", "deepseek-flash"))
    cloud_key: str = field(default_factory=lambda: _env("BRONE_DEEPSEEK_API_KEY", ""))
    mode: str = field(default_factory=lambda: _env("BRONE_MODE", "auto").lower())   # auto|cloud|local|faq
    cloud_timeout_s: float = field(default_factory=lambda: _env_f("BRONE_CLOUD_TIMEOUT_SECONDS", 8.0))
    local_timeout_s: float = field(default_factory=lambda: _env_f("BRONE_LOCAL_TIMEOUT_SECONDS", 25.0))
    max_tokens: int = field(default_factory=lambda: _env_i("BRONE_LLM_MAX_TOKENS", 160))
    faq_min_sim: float = field(default_factory=lambda: _env_f("BRONE_FAQ_MIN_SIM", 0.80))
    faq_min_margin: float = field(default_factory=lambda: _env_f("BRONE_FAQ_MIN_MARGIN", 0.0))
    stt_min_mean: float = field(default_factory=lambda: _env_f("BRONE_FAQ_STT_MIN_MEAN", 0.50))
    stt_min_seg: float = field(default_factory=lambda: _env_f("BRONE_FAQ_STT_MIN_SEG", 0.40))
    # STT kurang yakin -> FAQ tetap boleh, asal kemiripannya setinggi ini (lihat AnswerEngine.answer).
    faq_low_stt_min_sim: float = field(default_factory=lambda: _env_f("BRONE_FAQ_LOW_STT_MIN_SIM", 0.90))
    rerank_min: float = field(default_factory=lambda: _env_f("BRONE_RERANK_MIN", 0.30))
    rerank_top: int = field(default_factory=lambda: _env_i("BRONE_RERANK_TOP", 8))
    rerank_doc_chars: int = field(default_factory=lambda: _env_i("BRONE_RERANK_DOC_CHARS", 700))
    rerank_timeout_s: float = field(default_factory=lambda: _env_f("BRONE_RERANK_TIMEOUT_SECONDS", 10.0))
    context_chars: int = field(default_factory=lambda: _env_i("BRONE_CONTEXT_CHARS", 1400))
    context_chunks: int = field(default_factory=lambda: _env_i("BRONE_CONTEXT_CHUNKS", 4))
    grounding: bool = field(default_factory=lambda: _env("BRONE_GROUNDING", "1") not in ("0", "false", "no"))
    startup_wait_s: float = field(default_factory=lambda: _env_f("BRONE_SERVER_WAIT_SECONDS", 120.0))

class AnswerEngine:
    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.embedder = Embedder(cfg.embed_url, cfg.runtime_dir / "embcache.json")
        self.reranker = Reranker(cfg.rerank_url, timeout_s=cfg.rerank_timeout_s)
        entities = json.loads((cfg.kb_dir / "entities.json").read_text(encoding="utf-8"))
        self.entities = EntityMatcher(entities)
        self.faq = FaqIndex(cfg.kb_dir / "faq.jsonl", self.embedder, self.entities, cfg.faq_min_sim, cfg.faq_min_margin)
        self.retriever = HybridRetriever(cfg.kb_dir / "chunks.jsonl", self.embedder)
        self.cloud = LLMBackend("cloud", cfg.cloud_url, cfg.cloud_model, cfg.cloud_key, cfg.cloud_timeout_s,
                                cfg.max_tokens, {"thinking": {"type": "disabled"}}) if cfg.cloud_key else None
        # LFM2.5 adalah model "berpikir": tanpa --reasoning-budget 0 di server (dan kwarg ini) seluruh
        # max_tokens habis untuk penalaran berbahasa Inggris dan jawabannya kosong.
        self.local = LLMBackend("local", cfg.local_url.rstrip("/") + "/v1/chat/completions", cfg.local_model, "",
                                cfg.local_timeout_s, cfg.max_tokens,
                                {"chat_template_kwargs": {"enable_thinking": False}})
        self.turn_log = cfg.runtime_dir / "turns.jsonl"
        self.prev_question = ""

    def start(self) -> None:
        t0 = time.perf_counter()
        self.embedder.start(self.cfg.startup_wait_s)
        self.faq.build()
        self.retriever.build()
        self.embedder.save()
        self.reranker.start(self.cfg.startup_wait_s)
        if self.cfg.mode in ("auto", "local") and not wait_for_server(self.cfg.local_url, self.cfg.startup_wait_s):
            LOG.warning("LLM lokal %s belum siap; cadangan lokal tidak tersedia sampai server hidup", self.cfg.local_url)
        LOG.info("Mesin v4 siap dalam %.1fs: %d FAQ (%d kalimat), %d chunk, cloud=%s, mode=%s",
                 time.perf_counter() - t0, len(self.faq.faqs), len(self.faq._texts), len(self.retriever.chunks),
                 "ya" if self.cloud else "tidak", self.cfg.mode)

    def reset(self) -> None:
        self.prev_question = ""

    # -- util
    def _stt_ok(self, stt: dict | None) -> tuple[bool, str]:
        if not stt or "stt_mean_prob" not in stt:
            return True, "tanpa skor (input teks)"
        ok = stt["stt_mean_prob"] >= self.cfg.stt_min_mean and stt["stt_min_prob"] >= self.cfg.stt_min_seg
        return ok, f"stt_mean={stt['stt_mean_prob']:.2f} stt_min={stt['stt_min_prob']:.2f}"

    def _log(self, rec: dict) -> None:
        try:
            with self.turn_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _result(self, route: str, response: str, expression: str, rec: dict, t0: float) -> dict:
        rec.update(route=route, response=response, total_ms=round((time.perf_counter() - t0) * 1000))
        self._log(rec)
        LOG.info("v4 %s %dms: %r", route, rec["total_ms"], response[:120])
        return {"type": "question", "feature": "", "response": response, "expression": expression,
                "route": route, "meta": rec}

    # -- inti
    def answer(self, text: str, stt: dict | None = None) -> dict:
        t0 = time.perf_counter()
        text = text.strip()
        rec: dict[str, Any] = {"ts": _dt.datetime.now().isoformat(timespec="seconds"), "text": text, "stt": stt}
        if len(norm_text(text)) < 2:
            return self._result("tidak_dimengerti", MSG_NOT_UNDERSTOOD, "confused", rec, t0)

        qvec = self.embedder.embed([text])[0]
        rec["embed_ms"] = round((time.perf_counter() - t0) * 1000)

        # 2. FAQ. STT kurang yakin -> FAQ hanya bila kemiripannya sangat tinggi.
        # 14 Okt 2026: dulu FAQ dilewati sama sekali. Tetapi whisper-small memberi "Terima kasih." yang bersih
        # skor 0,38-0,62 (13 dari 24 di bawah 0,50; skor FAQ-nya 0,91-0,98), sedangkan gema prompt whisper
        # justru 0,40-0,79 -- skor STT tidak memisahkan ucapan asli dari sampah, dan teks yang dilewatkan
        # tetap berakhir di RAG/LLM. MAI tidak mengirim skor (selalu BRONE_MAI_DEFAULT_PROB).
        stt_ok, stt_note = self._stt_ok(stt)
        min_sim = None if stt_ok else self.cfg.faq_low_stt_min_sim
        rec["stt_gate"] = stt_note + (" -> FAQ boleh" if stt_ok else f" -> FAQ hanya bila skor >= {min_sim:.2f}")
        hit = self.faq.match(text, qvec, min_sim)
        if hit:
            rec["faq"] = {"id": hit.faq["id"], "score": round(hit.score, 4), "matched": hit.matched,
                          "margin": round(hit.margin, 4), "rejected": hit.rejected}
            self.prev_question = text
            return self._result("faq", hit.faq["a"], "happy", rec, t0)

        # 1. permintaan gerakan fisik (setelah FAQ, supaya "kamu bisa melambai?" dijawab FAQ)
        if _MOTION_RE.search(text) and not _MOTION_QUESTION_RE.search(text) and len(norm_text(text).split()) <= 5:
            return self._result("gerakan", MSG_MOTION, "neutral", rec, t0)
        if self.cfg.mode == "faq":
            return self._result("tolak_mode_faq", MSG_NO_INFO, "neutral", rec, t0)

        # 3. retrieval + reranker gate
        query = text
        if self.prev_question and len(norm_text(text).split()) <= 5:
            query = f"{self.prev_question} {text}"
            qvec = self.embedder.embed([query])[0]
        t1 = time.perf_counter()
        cand = self.retriever.search(query, qvec, top=self.cfg.rerank_top)
        try:
            scores = self.reranker.score(
                query, [self.retriever.chunks[i]["_doc"][: self.cfg.rerank_doc_chars] for i in cand])
        except Exception as exc:  # reranker mati: jangan tebak, tolak saja
            LOG.warning("Reranker gagal: %s", exc)
            rec["error"] = f"reranker: {exc}"
            return self._result("tolak_reranker_error", MSG_NO_INFO, "neutral", rec, t0)
        ranked = sorted(zip(cand, scores), key=lambda p: -p[1])
        rec["retrieval_ms"] = round((time.perf_counter() - t1) * 1000)
        rec["top"] = [(self.retriever.chunks[i]["id"], round(s, 3)) for i, s in ranked[:5]]
        if not ranked or ranked[0][1] < self.cfg.rerank_min:
            return self._result("tolak_tidak_ada_info", MSG_NO_INFO, "neutral", rec, t0)

        ctx_parts, used = [], 0
        for i, s in ranked[: self.cfg.context_chunks]:
            if s < self.cfg.rerank_min * 0.5 and ctx_parts:
                break
            doc = f"[{self.retriever.chunks[i]['judul']}] {self.retriever.chunks[i]['teks']}"
            if used + len(doc) > self.cfg.context_chars and ctx_parts:
                break
            ctx_parts.append(doc)
            used += len(doc)
        context = "\n".join(ctx_parts)
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"KONTEKS:\n{context}\n\nPERTANYAAN: {text}"}]

        # 4. LLM: cloud lalu lokal
        backends = {"auto": [self.cloud, self.local], "cloud": [self.cloud], "local": [self.local]}[self.cfg.mode]
        parsed, errors = None, []
        for be in [b for b in backends if b is not None]:
            try:
                raw, stats = be.chat(messages)
                rec["llm"] = {"backend": be.name, **stats}
                parsed = parse_llm_json(raw)
                if parsed is None:
                    errors.append(f"{be.name}: JSON tidak valid {raw[:80]!r}")
                    continue
                break
            except (OSError, urllib.error.URLError, ValueError, KeyError) as exc:
                errors.append(f"{be.name}: {str(exc)[:120]}")
                LOG.warning("LLM %s gagal: %s", be.name, exc)
        if errors:
            rec["llm_errors"] = errors
        if parsed is None:
            if errors and all("JSON" not in e for e in errors):
                return self._result("gagal_llm", MSG_SERVICE_DOWN, "confused", rec, t0)
            return self._result("tidak_dimengerti", MSG_NOT_UNDERSTOOD, "confused", rec, t0)

        response = str(parsed.get("response", "")).strip()
        expression = str(parsed.get("expression", "neutral")).lower()
        if expression not in {"happy", "neutral", "sad", "excited", "confused"}:
            expression = "neutral"
        if parsed.get("answerable") is False or not response:
            return self._result("tolak_llm", MSG_NO_INFO, "neutral", rec, t0)

        # 5. grounding
        if self.cfg.grounding:
            problems = grounding_problems(response, context, text)
            if problems:
                rec["grounding"] = problems
                rec["llm_response"] = response
                return self._result("tolak_grounding", MSG_NO_INFO, "neutral", rec, t0)
        self.prev_question = text
        return self._result(f"llm_{rec['llm']['backend']}", response, expression, rec, t0)
