"""Shared test fixtures: demo snapshot loader and a scripted fake LLM (no Ollama needed for unit tests)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from mcp_server.session import SafeSnapshot, SessionContext

AI_DIR = Path(__file__).resolve().parents[1]
DEMO = json.loads((AI_DIR / "mcp_server" / "demo_snapshot.json").read_text(encoding="utf-8"))


def snapshot(**overrides) -> SafeSnapshot:
    data = copy.deepcopy(DEMO)
    data.update(overrides)
    return SafeSnapshot.model_validate(data)


def context(**overrides) -> SessionContext:
    return SessionContext("unit-test-session", snapshot(**overrides))


class FakeLLM:
    """Returns scripted JSON objects in order and records the prompts it received."""

    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    async def chat_json(self, messages, schema, temperature=0.0, num_predict=700):
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self.responses.pop(0), 0.01
