"""Bot decision quality on hand-written scenarios (evaluation/bot_scenarios.py, never used for training).

Methods per scenario and question (answers checked against the acceptable set):
    heuristic            rule-based utility only (the teacher)
    laya                 Laya argmax only (feasible options; no RAG)
    blend                w * Laya + (1 - w) * heuristic, no RAG
    blend_rag            same, with RAG knowledge in the Laya state (same index as search_game_knowledge)
    laya_ft / blend_ft   the same with the fine-tuned checkpoint ai/models/laya-bot (if it exists)

Run:  cd ai && .venv\\Scripts\\python.exe ..\\evaluation\\bot_decision_eval.py [--base typed-decisions]
Output: evaluation/bot_decision_eval.csv (one row per scenario x question x method) + summary rows; console table.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai"))
sys.path.insert(0, str(ROOT / "evaluation"))

from agent.logging_utils import AgentLogger  # noqa: E402
from bot_scenarios import SCENARIOS  # noqa: E402
from decision import bot_decider, bot_heuristic as H, bot_rag  # noqa: E402
from decision.bot_config import BotConfig  # noqa: E402
from decision.injection_guard import InjectionGuard  # noqa: E402
from decision.laya_service import FINETUNED_DIR, LayaService, finetuned_available  # noqa: E402
from rag.retriever import KnowledgeIndex  # noqa: E402

OUT = ROOT / "evaluation" / "bot_decision_eval.csv"
QIDS = ("strategy", "next_unit", "threat_level", "attack_now", "target_zone", "build_next", "economy_focus",
        "maintenance")


def laya_choices(svc: LayaService, model: str, req, cfg: BotConfig, knowledge=None) -> tuple[dict, dict, float]:
    """Returns (laya argmax per question, raw laya option probabilities, laya_ms)."""
    questions = bot_decider.build_questions(req, cfg)
    state = bot_decider.build_state(req, knowledge, model)
    answers, ms = svc.predict(state, questions, model)
    decisions = bot_decider.to_decisions(answers, questions)
    return {d["id"]: d["choice"] for d in decisions}, decisions, ms


def decide_all(svc, model, req, cfg, index, guard, use_rag: bool):
    heur = H.heuristic(req, cfg, req.allowed_units, req.allowed_build, bot_decider.visible_zones(req), req.allowed_maintenance)
    knowledge, rag_ids = None, []
    if use_rag:
        rag = asyncio.run(bot_rag.enrich(req, index, guard, cfg, "eval_session_0000000", heur))
        knowledge, rag_ids = (rag.texts if rag.used else None), rag.source_ids
    laya_pick, decisions, ms = laya_choices(svc, model, req, cfg, knowledge)
    blended = {d["id"]: d["choice"] for d in bot_decider.blended_decisions(req, decisions, cfg, cfg.blend_weight)}
    # Laya-only: questions that were not asked (single feasible option) take that option
    laya_only = {q: laya_pick.get(q, H.argmax(heur[q]) if q in heur else "") for q in QIDS if q in heur}
    if "attack_now" in laya_only and "attack_now" in laya_pick:
        laya_only["attack_now"] = laya_pick["attack_now"]
    return laya_only, blended, rag_ids, decisions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="typed-decisions", help="base bot checkpoint (english / typed-decisions / multilingual)")
    ap.add_argument("--no-finetuned", action="store_true")
    args = ap.parse_args()

    cfg = BotConfig()
    index = KnowledgeIndex.load()
    base = LayaService(bot_model=args.base)
    base.load()
    if not base.ready:
        print("Laya not available:", base.error)
        sys.exit(1)
    guard = InjectionGuard(base, AgentLogger(enabled=False))
    ft = None
    if not args.no_finetuned and finetuned_available():
        ft = LayaService(bot_model=FINETUNED_DIR, guard_model="multilingual")
        ft.load()
        ft = ft if ft.ready else None
    print(f"device={base.device} base={base.bot_model} finetuned={'yes' if ft else 'no'} scenarios={len(SCENARIOS)}")

    rows = []
    for name, body, expected in SCENARIOS:
        req = bot_decider.BotDecideRequest.model_validate(body)
        heur = H.heuristic(req, cfg, req.allowed_units, req.allowed_build, bot_decider.visible_zones(req), req.allowed_maintenance)
        picks = {"heuristic": {q: H.argmax(d) for q, d in heur.items() if not q.startswith("_")}}
        lo, bl, _, dec = decide_all(base, base.bot_model, req, cfg, index, guard, use_rag=False)
        picks["laya"], picks["blend"] = lo, bl
        # sensitivity: a much stronger Laya weight (w = 0.8) on the same Laya answers
        picks["blend_w0.8"] = {d["id"]: d["choice"] for d in bot_decider.blended_decisions(req, dec, cfg, 0.8)}
        _, bl_rag, rag_ids, _ = decide_all(base, base.bot_model, req, cfg, index, guard, use_rag=True)
        picks["blend_rag"] = bl_rag
        if ft is not None:
            lo_ft, bl_ft, _, dec_ft = decide_all(ft, ft.bot_model, req, cfg, index, guard, use_rag=False)
            picks["laya_ft"], picks["blend_ft"] = lo_ft, bl_ft
            picks["blend_ft_w0.8"] = {d["id"]: d["choice"] for d in bot_decider.blended_decisions(req, dec_ft, cfg, 0.8)}
        for qid, ok_set in expected.items():
            for method, p in picks.items():
                got = p.get(qid, "")
                rows.append({"scenario": name, "question": qid, "method": method, "choice": got,
                             "expected": "|".join(sorted(ok_set)), "correct": int(got in ok_set),
                             "rag_source_ids": "|".join(rag_ids) if method == "blend_rag" else ""})

    methods = list(dict.fromkeys(r["method"] for r in rows))
    summary = []
    for m in methods:
        mr = [r for r in rows if r["method"] == m]
        acc = sum(r["correct"] for r in mr) / len(mr)
        per_scen = {}
        for r in mr:
            per_scen.setdefault(r["scenario"], []).append(r["correct"])
        full = sum(1 for v in per_scen.values() if all(v)) / len(per_scen)
        summary.append((m, len(mr), acc, full))

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["scenario", "question", "method", "choice", "expected", "correct", "rag_source_ids"])
        w.writeheader()
        w.writerows(rows)
        for m, n, acc, full in summary:
            w.writerow({"scenario": "SUMMARY", "question": f"checks={n}", "method": m, "choice": f"accuracy={acc:.3f}",
                        "expected": f"scenarios_all_correct={full:.3f}", "correct": "", "rag_source_ids": ""})
    print(f"{'method':<11} {'checks':>6} {'accuracy':>9} {'scenarios fully right':>22}")
    for m, n, acc, full in summary:
        print(f"{m:<11} {n:>6} {acc:>9.3f} {full:>22.3f}")
    print("written:", OUT)


if __name__ == "__main__":
    main()
