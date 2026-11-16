"""POST /plan/resolve: one small, genuinely ambiguous choice while an APPROVED plan item is turned into game commands.

Everything else in "Apply plan" is deterministic code in Unity (zone -> cell table, nearest suitable units, nearest
free build site). The only open choice is which VISIBLE enemy group an ATTACK item without target_type should hit
when the zone holds several groups. Unity asks this ahead of time (when the plan card is shown), with a short
timeout, and falls back to its deterministic default (the group closest to the zone centre). The Llama model is
never called while a plan is applied.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from decision.bot_decider import EnemyType, Region
from decision.laya_service import choice_options

_COUNTERED_BY = {"Cavalry": "Spearman", "Archer": "Cavalry", "Spearman": "Archer"}


class ResolveOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: EnemyType
    count: int = Field(ge=1, le=10_000)


class PlanResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=40)
    kind: Literal["attack_target"] = "attack_target"
    zone: Region
    attacker_type: Literal["", "Spearman", "Archer", "Cavalry"] = ""
    attacker_count: int = Field(default=1, ge=1, le=20)
    options: list[ResolveOption] = Field(min_length=2, max_length=6)


def build_question(req: PlanResolveRequest) -> tuple[str, dict]:
    attacker = req.attacker_type or "mixed army"
    state = (f"Approved attack order: {req.attacker_count} {attacker} units attack the {req.zone}. "
             "Visible enemy groups there: " + "; ".join(f"{o.id} x{o.count}" for o in req.options) + ".")
    criteria = {}
    for o in req.options:
        note = " (our attackers counter it)" if req.attacker_type and _COUNTERED_BY.get(o.id) == req.attacker_type else ""
        criteria[o.id] = f"{o.count} visible {o.id}{note}"
    question = {"target": {"type": "choice", "instructions": "Which visible enemy group should the attackers hit first?",
                           "criteria": criteria}}
    return state, question


def to_result(answers: dict, question: dict) -> dict:
    allowed = set(question["target"]["criteria"].keys())
    options = [o for o in choice_options(answers.get("target", {}) or {}) if o["label"] in allowed]
    if not options:
        return {"choice": "", "p": 0.0, "options": []}
    return {"choice": options[0]["label"], "p": options[0]["p"], "options": options}
