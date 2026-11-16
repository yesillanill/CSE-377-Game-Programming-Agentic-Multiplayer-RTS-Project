"""Laya decision engine wrapper: loaded ONCE in a background thread when the gateway starts, then kept in memory.

API used (verified against the installed laya 0.4.34 sources, laya/router.py):
    Router(device="cuda"|"cpu", vega=False, max_loaded=N)      # vega=False: no 0.8B vegaml reader lane
    router.preload(["multilingual", ...])                       # build checkpoints up front (no per-request load)
    router.predict(state, questions, model="multilingual")      # -> {"answers": {qid: {...}}, "routing": ..., ...}
    answers[qid]: choice -> {"choice", "probabilities": {label: p}}; score -> {"score", "probabilities": {"0": p..},
                  "legend": {"0": label..}}; noul -> {"noul": P(yes)}

Configuration (environment, all optional):
    RTS_LAYA_DISABLED=1          do not load Laya (layers fall back; gateway still works)
    RTS_LAYA_DEVICE=auto|cuda|cpu  default auto: CUDA when torch sees a GPU, otherwise CPU (logged)
    RTS_LAYA_BOT_MODEL           checkpoint for bot decisions: auto (default) | finetuned | typed-decisions | english |
                                 multilingual | <local checkpoint dir>.
                                 auto = ai/models/laya-bot (synthetic fine-tune, ai/laya_finetune) if it exists,
                                 otherwise the package's typed-decisions checkpoint, otherwise english. Logged at load.
    RTS_LAYA_GUARD_MODEL         checkpoint for injection screening, default "multilingual" (Turkish input needs it)

VRAM (RTX 4050, measured): multilingual ~1.3 GB, english / typed-decisions (ModernBERT-large) ~1.6 GB each. The same
GPU also runs the Llama model of the AI Commander; RTS_LAYA_BOT_MODEL=multilingual keeps a single resident checkpoint.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("laya")

KNOWN_MODELS = ("english", "multilingual", "typed-decisions")
FINETUNED_NAME = "bot-finetuned"
AI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINETUNED_DIR = os.path.join(AI_DIR, "models", "laya-bot")


def finetuned_available(path: str | None = None) -> bool:
    """True when a fine-tuned checkpoint exists (default: ai/models/laya-bot, read at call time)."""
    return os.path.isfile(os.path.join(path or FINETUNED_DIR, "rl_agent_config.json"))


class LayaUnavailable(RuntimeError):
    """Raised when a prediction is requested while the model is not loaded (loading / failed / disabled)."""


class LayaService:
    """Thread-safe holder of one preloaded laya.Router. One forward pass runs at a time (shared GPU weights)."""

    def __init__(self, bot_model: str | None = None, guard_model: str | None = None, device: str | None = None):
        self.bot_model_path: str | None = None
        self.bot_model = self._pick_bot(bot_model or os.environ.get("RTS_LAYA_BOT_MODEL", "auto"))
        # Turkish player messages must be read by the multilingual checkpoint (the English one collapses off-English)
        self.guard_model = self._pick(guard_model or os.environ.get("RTS_LAYA_GUARD_MODEL"), "multilingual")
        self.requested_device = (device or os.environ.get("RTS_LAYA_DEVICE", "auto")).strip().lower()
        self.status = "loading"           # loading | ready | failed | disabled
        self.device: str | None = None    # cuda | cpu once loaded
        self.error: str | None = None
        self.load_seconds: float | None = None
        self._router: Any = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _pick(value: str | None, default: str) -> str:
        value = (value or "").strip().lower()
        return value if value in KNOWN_MODELS else default

    def _pick_bot(self, value: str) -> str:
        """Bot checkpoint: fine-tuned (if present) > typed-decisions > english. See the module docstring."""
        value = (value or "auto").strip()
        if os.path.isdir(value) and finetuned_available(value):
            self.bot_model_path = value
            return FINETUNED_NAME
        low = value.lower()
        if low in ("auto", "finetuned") and finetuned_available():
            self.bot_model_path = globals()["FINETUNED_DIR"]
            return FINETUNED_NAME
        if low in KNOWN_MODELS:
            return low
        # auto without a fine-tune: the package ships typed-decisions (verified in laya/router.py DEFAULT_MODELS)
        try:
            from laya.router import DEFAULT_MODELS
            return "typed-decisions" if "typed-decisions" in DEFAULT_MODELS else "english"
        except Exception:  # noqa: BLE001 - laya missing: the load step reports it
            return "english"

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def models(self) -> list[str]:
        return sorted({self.bot_model, self.guard_model})

    @property
    def hub_models(self) -> list[str]:
        """Checkpoints the Router downloads / preloads by name (the fine-tune is attached separately)."""
        return [m for m in self.models if m in KNOWN_MODELS]

    # ------------------------------------------------------------------------------------------ loading
    def start_background_load(self) -> None:
        """Starts the one-time load without blocking the gateway (GET /health reports "loading" meanwhile)."""
        if os.environ.get("RTS_LAYA_DISABLED", "").strip() in ("1", "true", "yes"):
            self.status = "disabled"
            log.warning("Laya is disabled (RTS_LAYA_DISABLED). Bot uses its rule layer, the injection layer is off.")
            return
        self._thread = threading.Thread(target=self.load, name="laya-preload", daemon=True)
        self._thread.start()

    def load(self) -> None:
        started = time.perf_counter()
        try:
            import torch  # noqa: WPS433 - heavy import kept off the request path
            from laya import Router

            if self.requested_device == "cpu":
                device = "cpu"
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
                if self.requested_device == "cuda":
                    log.warning("RTS_LAYA_DEVICE=cuda but torch sees no CUDA GPU; Laya falls back to CPU.")
                else:
                    log.warning("No CUDA GPU visible to torch (CPU-only torch build?); Laya runs on CPU (slower).")

            router = Router(device=device, vega=False, max_loaded=max(2, len(self.models)))
            router.preload(self.hub_models)
            if self.bot_model == FINETUNED_NAME and self.bot_model_path:
                # Local fine-tuned checkpoint (ai/laya_finetune): same Router, registered under its own name
                import laya
                router.attach(FINETUNED_NAME, laya.load(self.bot_model_path, device=device))
            log.info("Laya bot checkpoint: %s%s", self.bot_model, f" ({self.bot_model_path})" if self.bot_model_path else "")
            # Warm-up: the first forward pass allocates kernels / caches; do it now, not on the first game request.
            # BOTH resident checkpoints are warmed: the first in-game /bot/decide must fit its 1.2 s timeout.
            warm_q = {"w": {"type": "noul", "instructions": "Is this a warm-up?"}}
            for model in dict.fromkeys((self.guard_model, self.bot_model)):
                router.predict("warm up", warm_q, model=model)
            self._router = router
            self.device = device
            self.load_seconds = round(time.perf_counter() - started, 1)
            self.status = "ready"
            gpu = f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""
            log.info("Laya ready on %s%s in %.1fs, checkpoints: %s", device, gpu, self.load_seconds, ", ".join(self.models))
        except Exception as exc:  # noqa: BLE001 - any failure only disables the Laya layers
            self.status = "failed"
            self.error = f"{type(exc).__name__}: {str(exc)[:200]}"
            log.warning("Laya could not be loaded (%s). The gateway keeps working without the Laya layers.", self.error)

    # ------------------------------------------------------------------------------------------ inference
    def predict(self, state: Any, questions: dict, model: str) -> tuple[dict, float]:
        """Runs one forward pass. Returns (answers, laya_ms). Raises LayaUnavailable when not loaded."""
        if self.status != "ready" or self._router is None:
            raise LayaUnavailable(self.status)
        with self._lock:
            t0 = time.perf_counter()
            out = self._router.predict(state, questions, model=model)
            ms = (time.perf_counter() - t0) * 1000.0
        return out.get("answers", {}), round(ms, 1)

    async def apredict(self, state: Any, questions: dict, model: str, timeout: float) -> tuple[dict, float]:
        """Async wrapper with a hard timeout (the forward pass runs in a worker thread, never on the event loop)."""
        return await asyncio.wait_for(asyncio.to_thread(self.predict, state, questions, model), timeout=timeout)

    def describe(self) -> dict:
        return {"status": self.status, "device": self.device or "none", "models": self.models, "bot_model": self.bot_model,
                "load_seconds": self.load_seconds, "error": self.error}


# ---------------------------------------------------------------------------------------------- answer helpers
def choice_options(answer: dict) -> list[dict]:
    """Normalizes a choice / score / noul answer to [{"label", "p"}] sorted by probability (Unity uses the first)."""
    if "noul" in answer and "probabilities" not in answer:
        p = float(answer.get("noul") or 0.0)
        opts = [{"label": "yes", "p": round(p, 4)}, {"label": "no", "p": round(1.0 - p, 4)}]
    else:
        probs = answer.get("probabilities") or {}
        legend = answer.get("legend") or {}
        opts = [{"label": str(legend.get(k, k)), "p": round(float(v), 4)} for k, v in probs.items()]
    opts.sort(key=lambda o: o["p"], reverse=True)
    return opts
