"""Deterministic stand-in for decision.laya_service.LayaService (unit tests run without GPU / model download)."""

from __future__ import annotations

import asyncio

_ATTACK_WORDS = ("ignore", "unut", "forget", "reveal", "gizli", "hidden", "system prompt", "koordinat")


class FakeLaya:
    """Same surface as LayaService: status / ready / device / models / predict / apredict."""

    def __init__(self, status: str = "ready", injection_p: float | None = None, delay: float = 0.0):
        self.status = status
        self.device = "cpu" if status == "ready" else None
        self.error = None if status == "ready" else "fake failure"
        self.load_seconds = 0.0
        self.bot_model = "multilingual"
        self.guard_model = "multilingual"
        self.injection_p = injection_p   # None: keyword heuristic
        self.delay = delay
        self.calls: list[tuple[str, list[str], str]] = []

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def models(self) -> list[str]:
        return ["multilingual"]

    def predict(self, state, questions, model):
        from decision.laya_service import LayaUnavailable
        if not self.ready:
            raise LayaUnavailable(self.status)
        self.calls.append((str(state), list(questions), model))
        text = str(state).lower()
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "noul":
                p = self.injection_p if self.injection_p is not None else (0.95 if any(w in text for w in _ATTACK_WORDS) else 0.02)
                answers[qid] = {"type": "noul", "noul": p}
            elif q["type"] == "score":
                answers[qid] = {"type": "score", "score": 1.0, "legend": {"0": "low", "1": "medium", "2": "high"},
                                "probabilities": {"0": 0.2, "1": 0.5, "2": 0.3}}
            else:
                labels = list(q["criteria"].keys())
                probs = {lab: (0.6 if i == len(labels) - 1 else 0.4 / max(1, len(labels) - 1)) for i, lab in enumerate(labels)}
                answers[qid] = {"type": "choice", "choice": labels[-1], "probabilities": probs}
        return answers, 1.0

    async def apredict(self, state, questions, model, timeout):
        async def run():
            if self.delay:
                await asyncio.sleep(self.delay)  # simulated slow forward pass (counts against the timeout)
            return await asyncio.to_thread(self.predict, state, questions, model)
        return await asyncio.wait_for(run(), timeout=timeout)
