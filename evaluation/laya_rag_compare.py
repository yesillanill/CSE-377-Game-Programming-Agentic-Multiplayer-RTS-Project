"""RAG vs no-RAG on the bot's next_unit decision (Laya alone and blended), >= 5 counter scenarios.

    cd ai && .venv\\Scripts\\python.exe ..\\evaluation\\laya_rag_compare.py
Output: evaluation/laya_rag_compare.csv
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai"))
sys.path.insert(0, str(ROOT / "evaluation"))

from agent.logging_utils import AgentLogger  # noqa: E402
from bot_scenarios import enemy, req, units, bld  # noqa: E402
from decision import bot_decider, bot_rag  # noqa: E402
from decision.bot_config import BotConfig  # noqa: E402
from decision.injection_guard import InjectionGuard  # noqa: E402
from decision.laya_service import LayaService  # noqa: E402
from rag.retriever import KnowledgeIndex  # noqa: E402

OUT = ROOT / "evaluation" / "laya_rag_compare.csv"

CASES = [  # (name, request, expected next_unit)
    ("cav8", req(own_units=units(12, spear=2, archer=2), visible_enemies=[enemy("Cavalry", 8)]), "spearman"),
    ("archer7", req(own_units=units(12, spear=3), resources={"wood": 300, "food": 400, "gold": 200},
                    own_buildings=bld(stable=True), visible_enemies=[enemy("Archer", 7, "North")]), "cavalry"),
    ("spear6", req(own_units=units(12, cav=2), resources={"wood": 300, "food": 300, "gold": 100},
                   visible_enemies=[enemy("Spearman", 6, "East")]), "archer"),
    ("cav3_mixed", req(own_units=units(12, archer=3), visible_enemies=[enemy("Cavalry", 3), enemy("Worker", 2)]), "spearman"),
    ("scifi_tanks", req(game_mode="SciFi", own_units=units(12, spear=1), visible_enemies=[enemy("Cavalry", 6, "NorthEast")]), "spearman"),
    ("scifi_snipers", req(game_mode="SciFi", own_units=units(12, spear=2), resources={"wood": 300, "food": 400, "gold": 200},
                          own_buildings=bld(stable=True), visible_enemies=[enemy("Archer", 5, "South")]), "cavalry"),
]


def main() -> None:
    cfg = BotConfig()
    svc = LayaService()
    svc.load()
    if not svc.ready:
        sys.exit(f"Laya not available: {svc.error}")
    index = KnowledgeIndex.load()
    guard = InjectionGuard(svc, AgentLogger(enabled=False))
    rows = []
    for name, body, expected in CASES:
        r = bot_decider.BotDecideRequest.model_validate(body)
        questions = bot_decider.build_questions(r, cfg)
        rag = asyncio.run(bot_rag.enrich(r, index, guard, cfg, "compare_session_0000"))
        out = {}
        for label, knowledge in (("no_rag", None), ("rag", rag.texts if rag.used else None)):
            answers, ms = svc.predict(bot_decider.build_state(r, knowledge, svc.bot_model), questions, svc.bot_model)
            dec = bot_decider.to_decisions(answers, questions)
            laya = next((d for d in dec if d["id"] == "next_unit"), None)
            blended = next(d for d in bot_decider.blended_decisions(r, dec, cfg, cfg.blend_weight) if d["id"] == "next_unit")
            out[label] = (laya["choice"] if laya else "", laya["p"] if laya else 0.0, blended["choice"], ms)
        rows.append({"scenario": name, "expected": expected, "model": svc.bot_model, "device": svc.device,
                     "rag_source_ids": "|".join(rag.source_ids),
                     "laya_no_rag": out["no_rag"][0], "laya_no_rag_p": out["no_rag"][1],
                     "laya_rag": out["rag"][0], "laya_rag_p": out["rag"][1],
                     "blend_no_rag": out["no_rag"][2], "blend_rag": out["rag"][2],
                     "laya_ms_no_rag": out["no_rag"][3], "laya_ms_rag": out["rag"][3], "rag_ms": rag.latency_ms})
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    for key in ("laya_no_rag", "laya_rag", "blend_no_rag", "blend_rag"):
        print(f"{key:<13} correct {sum(r[key] == r['expected'] for r in rows)}/{n}")
    print("written:", OUT)


if __name__ == "__main__":
    main()
