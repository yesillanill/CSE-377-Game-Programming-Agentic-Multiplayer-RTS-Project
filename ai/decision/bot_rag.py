"""RAG enrichment of the bot's Laya state: at most `max_records` short knowledge records ("knowledge" in the state).

Uses the SAME KnowledgeIndex object and the SAME `index.search(query, top_k)` call as the MCP tool
search_game_knowledge (mcp_server/server.py) — no second index is built.
  * counter record for the dominant VISIBLE enemy unit type (skipped when no enemy unit is visible)
  * cost / prerequisite record of the building the bot is close to choosing (heuristic top build_next, incl. Mine,
    DefenseTower, Wall, Farm)
Each retrieved chunk passes the existing Laya injection screen (InjectionGuard.screen_text) before it can enter the
state; a withheld chunk is logged by the guard. Any failure returns no records (the decision is made without RAG).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from decision import bot_heuristic as H
from decision.bot_config import BotConfig

log = logging.getLogger("bot.rag")

_BUILD_QUERY = {
    "house": "House population cost", "farm": "Farm food plot cost", "mine": "Mine gold income cost",
    "barracks": "Barracks cost trains", "stable": "Stable cavalry cost", "tower": "Archer Tower defense tower cost",
    "wall": "Wall segment cost",
}
_UNIT_RECORD = {"Cavalry": "unit_cavalry_v1", "Archer": "unit_archer_v1", "Spearman": "unit_spearman_v1"}


@dataclass
class RagResult:
    used: bool = False
    source_ids: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    withheld: list[str] = field(default_factory=list)
    error: str = ""
    searches: int = 0


def _short(text: str, limit: int, focus: str = "") -> str:
    """Whitespace-normalised text cut to `limit` chars. With `focus`, the part starting at that phrase is kept
    (e.g. a unit record's "strong against ... weak against ..." — a plain cut would drop the counter info)."""
    text = " ".join((text or "").split())
    if focus:
        i = text.lower().find(focus)
        if i > 0:
            head = text.split(" cost", 1)[0]          # "[unit] Cavalry (Sci-Fi mode name: Tank)"
            text = f"{head}: {text[i:]}"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def enrich(req, index, guard, cfg: BotConfig, session: str, heur: dict | None = None) -> RagResult:
    """Returns up to cfg.max_records shortened, injection-screened records. Never raises."""
    res = RagResult()
    if not cfg.rag_enrichment_enabled or cfg.max_records <= 0 or index is None:
        return res
    t0 = time.perf_counter()
    try:
        f = H.facts(req)
        queries: list[tuple[str, str]] = []
        dominant = f["dominant_enemy"]
        if dominant and dominant in _UNIT_RECORD:          # no visible enemy units -> no counter search
            queries.append((f"{dominant} counter strong weak", _UNIT_RECORD[dominant]))
        if heur is None:
            heur = H.heuristic(req, cfg, req.allowed_units, req.allowed_build)
        build_dist = heur.get("build_next") or {}
        top_build = H.argmax(build_dist) if build_dist else "none"
        if top_build != "none" and top_build in _BUILD_QUERY:
            queries.append((_BUILD_QUERY[top_build], ""))

        for query, preferred in queries:
            if len(res.texts) >= cfg.max_records:
                break
            res.searches += 1
            hits = index.search(query, 3)                 # same call as search_game_knowledge
            if not hits:
                continue
            hit = next((h for h in hits if preferred and h.get("source_id") == preferred), hits[0])
            sid = hit.get("source_id", "?")
            if sid in res.source_ids:
                continue
            text = _short(hit.get("text", ""), cfg.max_chars_per_record, "strong against" if preferred else "")
            if guard is not None and guard.enabled:
                verdict = await guard.screen_text(text, session, "bot_rag_chunk")
                if verdict.action == "blocked":
                    res.withheld.append(sid)
                    log.warning("Bot RAG chunk %s withheld by the injection screen.", sid)
                    continue
            res.source_ids.append(sid)
            res.texts.append(f"[{sid}] {text}")
        res.used = bool(res.texts)
    except Exception as exc:  # noqa: BLE001 - RAG is optional; decide without it
        res = RagResult(error=type(exc).__name__)
        log.warning("Bot RAG enrichment failed (%s); deciding without RAG.", res.error)
    res.latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return res
