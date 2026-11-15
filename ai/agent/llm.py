"""Minimal async Ollama chat client (provider-specific part of the agent; everything else is provider-neutral).

Configuration (environment variables):
    RTS_OLLAMA_URL   default http://127.0.0.1:11434
    RTS_AI_MODEL     default llama3.1:8b
    RTS_LLM_TIMEOUT  default 90 (seconds per LLM call)
"""

from __future__ import annotations

import json
import os
import time

import httpx

OLLAMA_URL = os.environ.get("RTS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("RTS_AI_MODEL", "llama3.1:8b")
TIMEOUT = float(os.environ.get("RTS_LLM_TIMEOUT", "90"))


class LLMError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_URL, model: str = MODEL, timeout: float = TIMEOUT):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict:
        try:
            r = await self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            r.raise_for_status()
            models = [m.get("name") for m in r.json().get("models", [])]
            return {"reachable": True, "model": self.model, "model_installed": self.model in models}
        except Exception as exc:  # noqa: BLE001 - health check reports any failure
            return {"reachable": False, "model": self.model, "model_installed": False, "error": type(exc).__name__}

    async def chat_json(self, messages: list[dict], schema: dict, temperature: float = 0.0,
                        num_predict: int = 700) -> tuple[dict, float]:
        """Runs one chat completion constrained to `schema` (Ollama structured outputs). Returns (object, seconds)."""
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "messages": messages,
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": 8192},
        }
        started = time.perf_counter()
        try:
            r = await self._client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama is not reachable at {self.base_url} ({type(exc).__name__}).") from exc
        elapsed = time.perf_counter() - started
        if r.status_code != 200:
            raise LLMError(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")
        content = r.json().get("message", {}).get("content", "")
        try:
            return json.loads(content), elapsed
        except json.JSONDecodeError as exc:
            raise LLMError("Model output was not valid JSON.") from exc
