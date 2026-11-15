"""ActionPlan normalization + validation.

Stage 1 (structural, here): every action proposed by the LLM is normalized (display names such as "Marine" or
"Mızrakçı" -> canonical "Spearman") and validated against schemas/action_plan.schema.json. Actions that fail the
schema never reach Unity; they are returned in `rejected` with the reason.

Stage 2 (gameplay pre-check, here): `precheck_actions` mirrors Unity's GameActionValidator rules (required
building, affordability, population, research busy / max tier) against the snapshot. It only annotates warnings
for the player and for evaluation metrics - the authoritative check is GameActionValidator in Unity, which runs
again on APPROVE against the live state.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from mcp_server import catalog
from mcp_server.session import SafeSnapshot

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "action_plan.schema.json"
MAX_TRAINING_QUEUE = 5  # Building.MaxTrainingQueueSize in Unity


@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _plan_validator() -> Draft202012Validator:
    return Draft202012Validator(schema())


@lru_cache(maxsize=1)
def _action_validator() -> Draft202012Validator:
    s = schema()
    return Draft202012Validator({"$schema": s["$schema"], "$defs": s["$defs"], "$ref": "#/$defs/action"})


def _err(errors) -> str:
    e = errors[0]
    where = "/".join(str(p) for p in e.absolute_path) or "action"
    return f"{where}: {e.message}"[:200]


def normalize_action(raw: dict) -> dict:
    """Canonicalizes names and drops empty optional fields. Unknown values are kept so the schema rejects them."""
    if not isinstance(raw, dict):
        return {"action_type": str(raw)}
    out: dict = {}
    for key, value in raw.items():
        if value is None or value == "" or value == []:
            continue
        out[key] = value
    if isinstance(out.get("action_type"), str):
        out["action_type"] = out["action_type"].strip().upper().replace(" ", "_")
    if isinstance(out.get("unit_type"), str):
        out["unit_type"] = catalog.canonical_unit(out["unit_type"]) or out["unit_type"]
    if isinstance(out.get("building_type"), str):
        out["building_type"] = catalog.canonical_building(out["building_type"]) or out["building_type"]
    if isinstance(out.get("tech_line"), str):
        line = out["tech_line"].strip().lower()
        out["tech_line"] = {"weapons": "weapon", "armour": "armor", "walls": "wall", "silah": "weapon", "zirh": "armor",
                            "zırh": "armor", "duvar": "wall"}.get(line, line)
    if isinstance(out.get("resource_type"), str):
        out["resource_type"] = catalog.canonical_resource(out["resource_type"]) or out["resource_type"]
    if isinstance(out.get("target_type"), str):
        out["target_type"] = catalog.canonical_target(out["target_type"]) or out["target_type"]
    if isinstance(out.get("target_zone"), str):
        out["target_zone"] = catalog.canonical_region(out["target_zone"]) or out["target_zone"]
    # Fields that do not belong to the action type are removed (the model fills every schema slot).
    allowed = {
        "TRAIN_UNIT": {"unit_type", "count"},
        "BUILD": {"building_type"},
        "RESEARCH": {"tech_line"},
        "MOVE_GROUP": {"unit_type", "target_zone"},
        "ATTACK": {"unit_type", "count", "target_zone", "target_type"},
        "GATHER": {"resource_type", "count"},
    }.get(out.get("action_type"))
    if allowed is not None:
        out = {k: v for k, v in out.items() if k in allowed or k in ("action_type", "reason")}
    if "reason" in out and isinstance(out["reason"], str):
        out["reason"] = out["reason"][:250]
    else:
        out.setdefault("reason", "")
    return out


def max_plan_actions() -> int:
    """Plan başına en fazla aksiyon: tek kaynak action_plan.schema.json içindeki maxItems (Unity AiPlanSchema ile aynı)."""
    return int(schema()["properties"]["actions"]["maxItems"])


def validate_plan(plan: dict) -> list[str]:
    return [_err([e]) for e in sorted(_plan_validator().iter_errors(plan), key=lambda e: list(e.absolute_path))]


def build_plan(summary: str, confidence: float, raw_actions: list, max_actions: int | None = None) -> tuple[dict, list[dict]]:
    """Returns (schema-valid plan, rejected actions with reasons)."""
    max_actions = min(max_actions or max_plan_actions(), max_plan_actions())
    actions, rejected = [], []
    for raw in (raw_actions or [])[:32]:  # fazlası sessizce kırpılmaz: max_actions sonrası "rejected" listesine girer
        action = normalize_action(raw)
        errors = list(_action_validator().iter_errors(action))
        if errors:
            rejected.append({"action": action, "reason": _err(errors), "stage": "schema"})
        elif len(actions) >= max_actions:
            rejected.append({"action": action, "reason": f"plan limited to {max_actions} actions", "stage": "schema"})
        else:
            actions.append(action)
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        conf = 0.5
    plan = {"summary": (summary or "")[:400], "confidence": min(1.0, max(0.0, conf)), "actions": actions}
    problems = validate_plan(plan)
    if problems:  # defensive: should not happen after per-action validation
        raise ValueError("; ".join(problems))
    return plan, rejected


def precheck_actions(actions: list[dict], snap: SafeSnapshot) -> list[str]:
    """Mirror of GameActionValidator: returns one warning ("" = looks legal) per action, simulated in order."""
    res = snap.resources.model_dump()
    pop_free = max(0, snap.population.max - snap.population.current - snap.population.queued)
    completed: dict[str, int] = {}
    for b in snap.own_buildings:
        completed[b.type] = completed.get(b.type, 0) + max(0, b.count - b.under_construction)
    workers = sum(u.count for u in snap.own_units if u.type == "Worker")
    military: dict[str, int] = {}
    for u in snap.own_units:
        if u.type != "Worker":
            military[u.type] = military.get(u.type, 0) + u.count
    levels = {"weapon": snap.tech.weapon_level, "armor": snap.tech.armor_level, "wall": snap.tech.wall_level}
    researching = bool(snap.tech.researching)
    idle_workers = sum(u.idle for u in snap.own_units if u.type == "Worker")

    def pay(cost: dict) -> str:
        short = {k: cost[k] - res[k] for k in cost if cost[k] > res[k]}
        if short:
            return "Not enough resources (" + ", ".join(f"{v} {k}" for k, v in short.items()) + " missing)"
        for k in cost:
            res[k] -= cost[k]
        return ""

    warnings = []
    for a in actions:
        t = a["action_type"]
        w = ""
        if t == "TRAIN_UNIT":
            producer = catalog.producer_of(a["unit_type"])
            n = completed.get(producer, 0)
            if n == 0:
                w = f"Required building missing: {producer}"
            elif a["count"] > n * MAX_TRAINING_QUEUE:
                w = f"Training queue is full (max {MAX_TRAINING_QUEUE} per {producer})"
            elif a["count"] > pop_free:
                w = f"Population limit reached ({pop_free} free)"
            else:
                w = pay(catalog.cost_of("unit", a["unit_type"], a["count"]))
                if not w:
                    pop_free -= a["count"]
        elif t == "BUILD":
            w = "No Worker available to build" if workers == 0 else pay(catalog.cost_of("building", a["building_type"]))
        elif t == "RESEARCH":
            line = a["tech_line"]
            if completed.get("Blacksmith", 0) == 0:
                w = "Required building missing: Blacksmith"
            elif researching:
                w = "Another research is already in progress"
            elif levels[line] >= catalog.max_level(line):
                w = f"{line} upgrades are already at the maximum tier"
            else:
                w = pay(catalog.cost_of("tech", line, 1, levels))
                if not w:
                    researching = True
                    levels[line] += 1
        elif t == "MOVE_GROUP":
            pool = military.get(a.get("unit_type", ""), 0) if a.get("unit_type") else sum(military.values())
            if a.get("unit_type") == "Worker":
                w = "Workers are not moved by MOVE_GROUP"
            elif pool == 0:
                w = "No matching military units to move"
        elif t == "ATTACK":
            # Mirror of GameActionValidator.ValidateAttackOrder: target must be visible NOW (fog of war)
            zone, ttype = a["target_zone"], a.get("target_type")
            visible = [e for e in snap.visible_enemies if e.region == zone and (not ttype or e.type == ttype)]
            visible += [b for b in snap.visible_enemy_buildings if b.region == zone and (not ttype or b.type == ttype)]
            utype = a.get("unit_type")
            if utype == "Worker":
                w = "Only combat units can attack."
            elif not visible:
                w = "Target is not visible."
            else:
                have = military.get(utype, 0) if utype else sum(military.values())
                if have < a["count"]:
                    w = f"Not enough combat units (have {have}, need {a['count']})."
        elif t == "GATHER":
            # Mirror of GameActionValidator.ValidateGatherOrder (explored-source check only exists in Unity)
            if idle_workers < a["count"]:
                w = f"Not enough idle workers (have {idle_workers}, need {a['count']})."
            else:
                idle_workers -= a["count"]
        warnings.append(w)
    return warnings
