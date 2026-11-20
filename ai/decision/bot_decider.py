"""POST /bot/decide: the VsAI bot's strategic decision layer.

Unity (BotController.cs) sends a SHORT, fog-of-war-safe summary of the bot team: its own resources, units, buildings,
research and ONLY the enemies the bot team can currently see (VisibilityService.GetVisibleEnemies(botTeam)).
There is no field for hidden enemy data; unknown fields are rejected (extra="forbid").

Pipeline (gateway/app.py):
  1. hard constraints: options the validator would reject (unaffordable / missing building / caps) are removed
     BEFORE Laya is asked (candidate_* in bot_heuristic + the allowed_* lists Unity computed with its validator)
  2. optional RAG enrichment (decision/bot_rag.py): <= 2 short records from the SAME index search_game_knowledge uses
  3. Laya answers the remaining typed questions in ONE forward pass over a fixed-order English state template
  4. every answer is blended with the rule-based utility: final = w * Laya + (1 - w) * heuristic
Unity takes the highest blended option of each question (its own C# copy of the heuristic is authoritative in game).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from decision import bot_heuristic as H
from decision.bot_config import BotConfig
from decision.laya_service import choice_options

Region = Literal["NorthWest", "North", "NorthEast", "West", "Center", "East", "SouthWest", "South", "SouthEast", "Unknown"]
UnitName = Literal["Worker", "Spearman", "Archer", "Cavalry"]
EnemyType = Literal["Worker", "Spearman", "Archer", "Cavalry", "TownCenter", "House", "Barracks", "Stable",
                    "Blacksmith", "Mine", "DefenseTower", "Wall", "HealthCenter", "Farm"]
BuildingName = Literal["TownCenter", "House", "Barracks", "Stable", "Blacksmith", "Mine", "DefenseTower", "Wall", "HealthCenter",
                       "Farm"]

MAX_TARGET_ZONES = 6          # keep choice questions small (Laya accuracy drops with many options)
# State budgets in characters (~3.5 chars per token). English checkpoint: 512 tokens incl. the question head (<= 192)
# -> ~320 tokens for the state; multilingual / typed-decisions: 1024 tokens incl. head (<= 256).
STATE_CHAR_BUDGET = {"english": 1000, "multilingual": 2400, "typed-decisions": 2400}
DEFAULT_CHAR_BUDGET = 1000    # unknown (e.g. fine-tuned) checkpoints: the conservative budget


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=40)


class BotResources(_Strict):
    wood: int = Field(ge=0, le=1_000_000)
    food: int = Field(ge=0, le=1_000_000)
    gold: int = Field(ge=0, le=1_000_000)


class BotPopulation(_Strict):
    current: int = Field(ge=0, le=10_000)
    max: int = Field(ge=0, le=10_000)


class BotUnitCount(_Strict):
    type: UnitName
    count: int = Field(ge=0, le=10_000)


class BotBuildingCount(_Strict):
    type: BuildingName
    count: int = Field(ge=0, le=10_000)
    under_construction: int = Field(default=0, ge=0, le=10_000)


class BotVisibleEnemy(_Strict):
    type: EnemyType
    count: int = Field(ge=1, le=10_000)
    region: Region


class BotEvent(_Strict):
    # FIRE / PLAGUE: disasters of the bot's OWN team only (Unity never sends the opponent's disasters)
    type: Literal["UNDER_ATTACK", "UNIT_LOST", "BUILDING_LOST", "ENEMY_SPOTTED", "UNIT_TRAINED", "BUILDING_COMPLETED",
                  "FIRE", "PLAGUE"]
    region: Region = "Unknown"
    seconds_ago: float = Field(ge=0, le=100_000)
    detail: str = ""   # e.g. building type for BUILDING_LOST / FIRE


class BotDecideRequest(_Strict):
    match_id: str = Field(min_length=1, max_length=64)
    game_mode: Literal["Medieval", "SciFi"] = "Medieval"
    game_time_seconds: float = Field(default=0.0, ge=0)
    resources: BotResources
    population: BotPopulation
    combat_units: int = Field(default=0, ge=0, le=10_000)
    idle_workers: int = Field(default=0, ge=0, le=10_000)
    wounded_units: int = Field(default=0, ge=0, le=10_000)      # own units below the Health Center threshold (30% HP)
    # Building maintenance (own buildings only): finished, not burning, no job yet; damaged = under 60% HP,
    # critical = non Town Center under 25% HP with an empty training queue; repair_cost = cost of the most damaged one
    damaged_buildings: int = Field(default=0, ge=0, le=10_000)
    critical_buildings: int = Field(default=0, ge=0, le=10_000)
    repair_cost: BotResources = Field(default_factory=lambda: BotResources(wood=0, food=0, gold=0))
    weapon_level: int = Field(default=0, ge=0, le=3)
    armor_level: int = Field(default=0, ge=0, le=4)
    own_power: float = Field(default=-1.0, ge=-1.0, le=1e12)      # -1: let the gateway compute it
    enemy_power: float = Field(default=-1.0, ge=-1.0, le=1e12)
    own_units: list[BotUnitCount] = Field(default_factory=list, max_length=8)
    own_buildings: list[BotBuildingCount] = Field(default_factory=list, max_length=16)
    researched: list[str] = Field(default_factory=list, max_length=16)
    visible_enemies: list[BotVisibleEnemy] = Field(default_factory=list, max_length=32)
    recent_events: list[BotEvent] = Field(default_factory=list, max_length=8)
    # Hard constraints computed by Unity with GameActionValidator (None/absent: the gateway's own checks only)
    allowed_units: list[Literal["worker", "spearman", "archer", "cavalry"]] | None = None
    allowed_build: list[Literal["none", "house", "farm", "mine", "barracks", "stable", "tower", "wall", "health_center"]] | None = None
    allowed_maintenance: list[Literal["none", "repair", "demolish"]] | None = None


# Option descriptions use the game's own values (costs from GameActionValidator / rag knowledge) so the options are distinct.
_UNIT_TEXT = {
    "Medieval": {
        "worker": "Worker 50 food: gathers wood, food and gold, builds; weak fighter",
        "spearman": "Spearman 60 food 20 gold: cheap infantry, strong vs cavalry, weak vs archer",
        "archer": "Archer 30 wood 40 food: ranged, strong vs spearman, weak vs cavalry",
        "cavalry": "Cavalry 80 food 40 gold: fast and tough, strong vs archer, weak vs spearman",
    },
    "SciFi": {
        "worker": "Engineer 50 food: gathers wood, food and gold, builds; weak fighter",
        "spearman": "Marine 60 food 20 gold: cheap infantry, strong vs tanks, weak vs snipers",
        "archer": "Sniper 30 wood 40 food: ranged, strong vs marines, weak vs tanks",
        "cavalry": "Tank 80 food 40 gold: fast and tough, strong vs snipers, weak vs marines",
    },
}
_BUILD_TEXT = {
    "none": "no new building now, save resources",
    "house": "House 30 wood: +5 population room",
    "farm": "Farm 10 wood: renewable food, 10 food seed returns 30",
    "mine": "Mine 75 gold: +10 gold every 10 s with one worker",
    "barracks": "Barracks 100 wood: trains spearmen and archers",
    "stable": "Stable 120 wood 20 gold: trains cavalry",
    "tower": "Tower 100 gold: manned defense, 12 damage, range 6.5",
    "wall": "Wall 10 wood per segment: blocks the enemy approach",
    "health_center": "Health Center 100 wood 50 gold: wounded units below 30% HP heal to full there",
}
_MAINT_TEXT = {
    "none": "no repair or demolition now, keep workers on the economy",
    "repair": "repair the most damaged building with one worker, pay part of its cost, back to full HP",
    "demolish": "demolish a nearly destroyed building with one worker, get 50% of its cost back before the enemy destroys it",
}
_FOCUS_TEXT = {
    "food": "food: workers, soldiers, farm seeds",
    "wood": "wood: houses, barracks, archers, farms, walls",
    "gold": "gold: spearmen, cavalry, mines, towers, upgrades",
}


def visible_zones(req: BotDecideRequest) -> list[str]:
    """Zones where the bot sees enemies RIGHT NOW (largest groups first, at most 6). Never any other zone."""
    totals: dict[str, int] = {}
    for e in req.visible_enemies:
        if e.region != "Unknown":
            totals[e.region] = totals.get(e.region, 0) + e.count
    return [z for z, _ in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))][:MAX_TARGET_ZONES]


def _count(items, t) -> int:
    return sum(i.count for i in items if i.type == t)


def build_state(req: BotDecideRequest, knowledge: list[str] | None = None, model: str = "english") -> str:
    """Fixed-order, short English template (always the same fields in the same order; Laya never shows it to players).
    The context budget is respected: knowledge is shortened first, then dropped."""
    f = H.facts(req)
    ratio = H.power_ratio(f, req)
    enemies = "; ".join(f"{e.type} {e.count} {e.region}" for e in req.visible_enemies[:10]) or "none"
    events = "; ".join(f"{e.type}{(' ' + e.detail) if e.detail else ''} {e.region} {int(e.seconds_ago)}s"
                       for e in req.recent_events[:5]) or "none"
    base = (f"Mode {req.game_mode}. Time {int(req.game_time_seconds)}s. "
            f"Resources wood {f['wood']} food {f['food']} gold {f['gold']}. "
            f"Population {f['pop']}/{f['pop_max']}. Workers {f['workers']} idle {f['idle_workers']}. "
            f"Army spearman {f['army']['Spearman']} archer {f['army']['Archer']} cavalry {f['army']['Cavalry']} "
            f"wounded {f['wounded']}. "
            f"Buildings barracks {f['barracks']} stable {f['stable']} blacksmith {f['blacksmith']} house {f['house']} "
            f"farm {f['farm']} mine {f['mine']} tower {f['tower']} wall {f['wall']} health center {f['health_center']}. "
            f"Damaged buildings {f['damaged_buildings']} critical {f['critical_buildings']}. "
            f"Upgrades weapon {f['weapon']} armor {f['armor']}. "
            f"Visible enemies: {enemies}. Power ratio: {'unknown' if ratio is None else f'{ratio:.1f}'}. "
            f"Events: {events}.")
    budget = STATE_CHAR_BUDGET.get(model, DEFAULT_CHAR_BUDGET)
    base = base[:budget]
    if knowledge:
        room = budget - len(base) - len(" Knowledge: .")
        if room >= 60:
            per = max(30, room // len(knowledge) - 3)
            parts = [k if len(k) <= per else k[: per - 1].rstrip() + "…" for k in knowledge]
            text = " | ".join(parts)
            if len(text) <= room:
                base += f" Knowledge: {text}."
    return base


def build_questions(req: BotDecideRequest, cfg: BotConfig | None = None) -> dict:
    """Typed questions over FEASIBLE options only. A question with fewer than 2 candidates is not asked."""
    cfg = cfg or BotConfig()
    f = H.facts(req)
    units_text = _UNIT_TEXT.get(req.game_mode, _UNIT_TEXT["Medieval"])
    questions: dict = {
        "strategy": {"type": "choice", "instructions": "Which overall strategy should the bot follow right now?",
                     "criteria": {"economy": "gather resources and train workers",
                                  "defend": "keep the army home and protect the base",
                                  "attack": "send the army against visible enemies",
                                  "tech": "research weapon and armor upgrades"}},
        "threat_level": {"type": "score", "instructions": "How dangerous are the visible enemies and recent attacks for the bot base?",
                         "criteria": ["low", "medium", "high"]},
        "attack_now": {"type": "noul", "instructions": "Is the bot army clearly stronger than the visible enemy army right now?"},
        "economy_focus": {"type": "choice", "instructions": "Which resource does the bot need most now?",
                          "criteria": dict(_FOCUS_TEXT)},
    }
    units = H.candidate_units(f, req.allowed_units)
    if len(units) >= 2:
        questions["next_unit"] = {"type": "choice", "instructions": "Which unit should the bot train next?",
                                  "criteria": {u: units_text[u] for u in units}}
    builds = H.candidate_builds(f, cfg, req.allowed_build)
    if len(builds) >= 2:
        questions["build_next"] = {"type": "choice", "instructions": "Which building should the bot construct next?",
                                   "criteria": {b: _BUILD_TEXT[b] for b in builds}}
    maint = H.candidate_maintenance(f, req.allowed_maintenance)
    if len(maint) >= 2:
        questions["maintenance"] = {"type": "choice", "instructions": "Should the bot repair or demolish one of its damaged buildings now?",
                                    "criteria": {m: _MAINT_TEXT[m] for m in maint}}
    zones = visible_zones(req)
    if len(zones) >= 1:
        totals = {z: sum(e.count for e in req.visible_enemies if e.region == z) for z in zones}
        if len(zones) >= 2:
            questions["target_zone"] = {"type": "choice", "instructions": "Which zone with visible enemies should the bot army target?",
                                        "criteria": {z: f"{totals[z]} visible enemies in the {z}" for z in zones}}
    return questions


def to_decisions(answers: dict, questions: dict) -> list[dict]:
    """[{"id", "type", "choice", "p", "options": [{"label", "p"}]}] in a JsonUtility-friendly shape (no dicts)."""
    out = []
    for qid, spec in questions.items():
        ans = answers.get(qid)
        if not isinstance(ans, dict):
            continue
        options = choice_options(ans)
        if spec["type"] == "choice":
            allowed = set(spec["criteria"].keys())
            options = [o for o in options if o["label"] in allowed]  # never return a label that was not offered
        if not options:
            continue
        out.append({"id": qid, "type": spec["type"], "choice": options[0]["label"], "p": options[0]["p"], "options": options})
    return out


def blended_decisions(req: BotDecideRequest, laya_decisions: list[dict] | None, cfg: BotConfig, w: float) -> list[dict]:
    """Final decision per question = w * Laya + (1 - w) * heuristic (w = 0 when Laya is unavailable).
    Questions that were not asked (fewer than 2 candidates) are answered by the heuristic alone."""
    zones = visible_zones(req)
    heur = H.heuristic(req, cfg, req.allowed_units, req.allowed_build, zones, req.allowed_maintenance)
    laya_by_id = {d["id"]: {o["label"]: o["p"] for o in d["options"]} for d in (laya_decisions or [])}
    out = []
    for qid in ("strategy", "next_unit", "threat_level", "attack_now", "target_zone", "build_next", "economy_focus",
                "maintenance"):
        h = heur.get(qid)
        if not h:
            continue
        final = H.blend(laya_by_id.get(qid), h, w if qid in laya_by_id else 0.0)
        opts = sorted(({"label": k, "p": round(v, 4)} for k, v in final.items()), key=lambda o: -o["p"])
        out.append({"id": qid, "type": "blend", "choice": H.argmax(final), "p": round(max(final.values()), 4), "options": opts,
                    "heuristic": H.argmax(h), "laya": H.argmax(laya_by_id[qid]) if qid in laya_by_id else ""})
    return out
