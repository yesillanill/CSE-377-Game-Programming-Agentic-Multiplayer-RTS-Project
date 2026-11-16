"""Configuration of the VsAI bot decision layer (environment variables, all optional; ai/.env is read by the gateway).

    RTS_RAG_ENRICHMENT          rag_enrichment_enabled, default true: add short knowledge records to the Laya state
    RTS_RAG_MAX_RECORDS         max_records, default 2
    RTS_RAG_MAX_CHARS           max_chars_per_record, default 200
    RTS_BLEND_WEIGHT            w in  final = w * Laya + (1 - w) * heuristic, default 0.4 (0 when Laya is unavailable)
    RTS_ATTACK_RATIO            attack only when own power / visible enemy power >= this, default 1.3
    RTS_MIN_ARMY                minimum combat units for an attack, default 4
    RTS_MAX_TOWERS              upper bound of bot towers, default 3
    RTS_MAX_DEFENSE_SHARE       max share of spent resources for towers + walls, default 0.25
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class BotConfig:
    rag_enrichment_enabled: bool = True
    max_records: int = 2
    max_chars_per_record: int = 200
    blend_weight: float = 0.4
    attack_ratio: float = 1.3
    min_army: int = 4
    max_towers: int = 3
    max_defense_share: float = 0.25

    @classmethod
    def from_env(cls) -> "BotConfig":
        return cls(
            rag_enrichment_enabled=_flag("RTS_RAG_ENRICHMENT", True),
            max_records=max(0, int(os.environ.get("RTS_RAG_MAX_RECORDS", "2"))),
            max_chars_per_record=max(40, int(os.environ.get("RTS_RAG_MAX_CHARS", "200"))),
            blend_weight=min(1.0, max(0.0, float(os.environ.get("RTS_BLEND_WEIGHT", "0.4")))),
            attack_ratio=max(0.5, float(os.environ.get("RTS_ATTACK_RATIO", "1.3"))),
            min_army=max(1, int(os.environ.get("RTS_MIN_ARMY", "4"))),
            max_towers=max(0, int(os.environ.get("RTS_MAX_TOWERS", "3"))),
            max_defense_share=min(1.0, max(0.0, float(os.environ.get("RTS_MAX_DEFENSE_SHARE", "0.25")))),
        )
