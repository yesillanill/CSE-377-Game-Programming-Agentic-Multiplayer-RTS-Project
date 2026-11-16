"""Synthetic training data for the bot's Laya checkpoint.

Random but VALID game states (resources, army, visible enemy compositions, disaster / attack events, building counts incl.
farms, mines, towers, walls) -> the exact state text and typed questions the gateway sends (bot_decider.build_state /
build_questions, so training and inference use the same template) -> labels from the TEACHER (bot_heuristic argmax).
About half of the states carry the RAG "Knowledge:" field like a real request (same index as search_game_knowledge).
The hand-written evaluation scenarios (evaluation/bot_scenarios.py) are excluded by state hash.

    cd ai && .venv\\Scripts\\python.exe -m laya_finetune.generate_dataset --rows 4000
Output: ai/models/laya-bot-data/{train,val}.jsonl   ({"state", "questions", "expected"} rows, laya.train format)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI_DIR))
sys.path.insert(0, str(AI_DIR.parent / "evaluation"))

from decision import bot_decider, bot_heuristic as H, bot_rag  # noqa: E402
from decision.bot_config import BotConfig  # noqa: E402
from rag.retriever import KnowledgeIndex  # noqa: E402

REGIONS = ["NorthWest", "North", "NorthEast", "West", "Center", "East", "SouthWest", "South", "SouthEast"]
OUT_DIR = AI_DIR / "models" / "laya-bot-data"


def random_state(rng: random.Random) -> dict:
    workers = rng.randint(2, 20)
    spear, archer, cav = rng.randint(0, 10), rng.randint(0, 10), rng.randint(0, 8)
    has_barracks = rng.random() < 0.8
    has_stable = has_barracks and rng.random() < 0.4
    blds = [{"type": "TownCenter", "count": 1, "under_construction": 0}]
    if has_barracks:
        blds.append({"type": "Barracks", "count": 1, "under_construction": int(rng.random() < 0.1)})
    if has_stable:
        blds.append({"type": "Stable", "count": 1, "under_construction": 0})
    for t, mx in (("House", 4), ("Farm", 10), ("Mine", 3), ("DefenseTower", 3), ("Wall", 12), ("Blacksmith", 1)):
        n = rng.randint(0, mx) if rng.random() < 0.5 else 0
        if n:
            blds.append({"type": t, "count": n, "under_construction": 0})
    if not has_barracks:
        spear = archer = 0
    if not has_stable:
        cav = 0
    army = spear + archer + cav
    pop = workers + army
    cap = max(pop, rng.choice([15, 20, 25, 30, 35]))
    enemies = []
    for _ in range(rng.choice([0, 0, 1, 1, 2, 3])):
        enemies.append({"type": rng.choice(["Spearman", "Archer", "Cavalry", "Cavalry", "Worker", "Barracks", "House"]),
                        "count": rng.randint(1, 10), "region": rng.choice(REGIONS)})
    events = []
    for _ in range(rng.choice([0, 0, 1, 2, 3])):
        t = rng.choice(["UNDER_ATTACK", "UNDER_ATTACK", "UNIT_LOST", "FIRE", "PLAGUE", "BUILDING_LOST", "ENEMY_SPOTTED"])
        detail = rng.choice(["Barracks", "House", "Stable", "Mine", "DefenseTower"]) if t in ("FIRE", "BUILDING_LOST") else ""
        events.append({"type": t, "region": rng.choice(REGIONS), "seconds_ago": round(rng.uniform(1, 110), 1), "detail": detail})
    return {
        "match_id": "synthetic", "game_mode": rng.choice(["Medieval", "SciFi"]), "game_time_seconds": round(rng.uniform(30, 1200), 1),
        "resources": {"wood": rng.choice([rng.randint(0, 80), rng.randint(80, 600)]),
                      "food": rng.choice([rng.randint(0, 80), rng.randint(80, 600)]),
                      "gold": rng.choice([rng.randint(0, 90), rng.randint(90, 400)])},
        "population": {"current": pop, "max": cap}, "combat_units": army, "idle_workers": rng.randint(0, min(3, workers)),
        "weapon_level": rng.choice([0, 0, 1, 2]), "armor_level": rng.choice([0, 0, 1, 2]),
        "own_units": [{"type": "Worker", "count": workers}, {"type": "Spearman", "count": spear},
                      {"type": "Archer", "count": archer}, {"type": "Cavalry", "count": cav}],
        "own_buildings": blds, "researched": [], "visible_enemies": enemies, "recent_events": events,
    }


def state_hash(req, model: str) -> str:
    return hashlib.sha256(bot_decider.build_state(req, None, model).encode("utf-8")).hexdigest()


def teacher_row(req, cfg: BotConfig, model: str, knowledge) -> dict:
    """{"state", "questions", "expected"}: exactly what the gateway would send, labelled by the heuristic."""
    questions = bot_decider.build_questions(req, cfg)
    heur = H.heuristic(req, cfg, req.allowed_units, req.allowed_build, bot_decider.visible_zones(req))
    expected = {}
    for qid, spec in questions.items():
        best = H.argmax(heur[qid])
        if spec["type"] == "noul":
            expected[qid] = best == "yes"
        elif spec["type"] == "score":
            # list criteria: laya.train expects the LEVEL INDEX ("low" -> 0); a label string is rejected as invalid_target
            expected[qid] = list(spec["criteria"]).index(best)
        else:
            expected[qid] = best
    return {"state": bot_decider.build_state(req, knowledge, model), "questions": questions, "expected": expected}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=4000)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--model", default="typed-decisions", help="template budget of the target checkpoint")
    args = ap.parse_args()

    from bot_scenarios import SCENARIOS
    cfg = BotConfig()
    index = KnowledgeIndex.load()
    excluded = {state_hash(bot_decider.BotDecideRequest.model_validate(b), args.model) for _, b, _ in SCENARIOS}
    rng = random.Random(args.seed)
    rows, seen, skipped = [], set(), 0
    while len(rows) < args.rows:
        req = bot_decider.BotDecideRequest.model_validate(random_state(rng))
        h = state_hash(req, args.model)
        if h in excluded or h in seen:
            skipped += 1
            continue
        seen.add(h)
        knowledge = None
        if rng.random() < 0.5:   # half of the states carry RAG knowledge like real requests
            rag = asyncio.run(bot_rag.enrich(req, index, None, cfg, "synthetic"))
            knowledge = rag.texts if rag.used else None
        rows.append(teacher_row(req, cfg, args.model, knowledge))

    rng.shuffle(rows)
    n_val = max(1, int(len(rows) * args.val_frac))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, part in (("val", rows[:n_val]), ("train", rows[n_val:])):
        with (OUT_DIR / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    q = sum(len(r["expected"]) for r in rows)
    print(f"rows={len(rows)} (train {len(rows) - n_val}, val {n_val}), labelled questions={q}, "
          f"skipped duplicates/eval-scenarios={skipped} -> {OUT_DIR}")


if __name__ == "__main__":
    main()
