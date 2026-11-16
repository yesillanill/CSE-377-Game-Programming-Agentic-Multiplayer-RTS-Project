"""Rule-based utility ("heuristic") for every bot question + power comparison + blending with Laya.

This is the Python mirror of UnityRTS/Assets/Scripts/Bot/BotPolicy.cs (Heuristic*, Power*, Blend). The Unity version is
authoritative in the game (it also runs when the gateway is down); this one is used by the gateway response, by
evaluation/bot_decision_eval.py and as the TEACHER for the synthetic Laya fine-tune (ai/laya_finetune). Both are kept
deliberately simple and are checked against the same fixture (ai/decision/heuristic_parity.json) in pytest and NUnit.

All functions are pure. Inputs come only from the bot's own state and the enemies it can currently see.
"""

from __future__ import annotations

from typing import Iterable

from decision.bot_config import BotConfig

# Medieval base stats (rag/knowledge/units.json; Unity uses the real UnitData values for the same formula)
UNIT_STATS = {"Worker": (40, 3), "Spearman": (80, 8), "Archer": (50, 9), "Cavalry": (100, 12)}
COUNTERS = {"Spearman": "Cavalry", "Archer": "Spearman", "Cavalry": "Archer"}   # key deals 2x damage to value
COMBAT = ("Spearman", "Archer", "Cavalry")
WEAPON_MULT = [1.0, 1.15, 1.30, 1.50]
ARMOR_RED = [0.0, 0.10, 0.20, 0.30, 0.40]

COSTS = {  # wood, food, gold (same as the Unity catalog / GameActionValidator defaults)
    "worker": (0, 50, 0), "spearman": (0, 60, 20), "archer": (30, 40, 0), "cavalry": (0, 80, 40),
    "house": (30, 0, 0), "farm": (10, 0, 0), "mine": (0, 0, 75), "barracks": (100, 0, 0), "stable": (120, 0, 20),
    "tower": (0, 0, 100), "wall": (60, 0, 0),  # wall: a short line of 6 segments x 10 wood
}

STRATEGIES = ("economy", "defend", "attack", "tech")
UNITS = ("worker", "spearman", "archer", "cavalry")
THREATS = ("low", "medium", "high")
BUILDS = ("none", "house", "farm", "mine", "barracks", "stable", "tower", "wall")
FOCUS = ("food", "wood", "gold")


# ---------------------------------------------------------------------------------------------- facts
def facts(req) -> dict:
    """Flattens the request (decision.bot_decider.BotDecideRequest) into the numbers the rules use."""
    units = {u.type: u.count for u in req.own_units}
    blds: dict[str, int] = {}
    pending: dict[str, int] = {}
    for b in req.own_buildings:
        blds[b.type] = blds.get(b.type, 0) + b.count
        pending[b.type] = pending.get(b.type, 0) + b.under_construction
    enemy_units = {}
    for e in req.visible_enemies:
        if e.type in UNIT_STATS:
            enemy_units[e.type] = enemy_units.get(e.type, 0) + e.count
    attacks = sum(1 for e in req.recent_events if e.type == "UNDER_ATTACK" and e.seconds_ago <= 90)
    lost = [e.detail for e in req.recent_events if e.type == "BUILDING_LOST" and e.detail]
    f = {
        "wood": req.resources.wood, "food": req.resources.food, "gold": req.resources.gold,
        "pop": req.population.current, "pop_max": req.population.max,
        "free_pop": req.population.max - req.population.current,
        "workers": units.get("Worker", 0), "idle_workers": req.idle_workers,
        "army": {t: units.get(t, 0) for t in COMBAT}, "army_n": sum(units.get(t, 0) for t in COMBAT),
        "barracks": blds.get("Barracks", 0), "stable": blds.get("Stable", 0), "blacksmith": blds.get("Blacksmith", 0),
        "house": blds.get("House", 0), "mine": blds.get("Mine", 0), "farm": blds.get("Farm", 0),
        "tower": blds.get("DefenseTower", 0), "wall": blds.get("Wall", 0), "town_center": blds.get("TownCenter", 0),
        "barracks_ready": blds.get("Barracks", 0) - pending.get("Barracks", 0) > 0,
        "stable_ready": blds.get("Stable", 0) - pending.get("Stable", 0) > 0,
        "enemy_units": enemy_units, "enemy_n": sum(enemy_units.values()),
        "enemy_seen": len(req.visible_enemies) > 0,
        "attacks": attacks, "fires": sum(1 for e in req.recent_events if e.type == "FIRE"),
        "plagues": sum(1 for e in req.recent_events if e.type == "PLAGUE"),
        "units_lost": sum(1 for e in req.recent_events if e.type == "UNIT_LOST"),
        "lost_buildings": lost,
        "weapon": req.weapon_level, "armor": req.armor_level,
    }
    f["dominant_enemy"] = max(enemy_units, key=lambda k: (enemy_units[k], k)) if enemy_units else ""
    return f


# ---------------------------------------------------------------------------------------------- power
def unit_power(unit: str, count: int, opponents: dict[str, int], weapon: int = 0, armor: int = 0) -> float:
    """count * hp * damage * counter multiplier (vs the opponent composition) * tech bonus."""
    if count <= 0:
        return 0.0
    hp, dmg = UNIT_STATS[unit]
    total = sum(opponents.values())
    if total > 0:
        mult = 0.0
        for e, n in opponents.items():
            m = 2.0 if COUNTERS.get(unit) == e else (0.5 if COUNTERS.get(e) == unit else 1.0)
            mult += m * n / total
    else:
        mult = 1.0
    tech = WEAPON_MULT[min(weapon, 3)] / max(0.4, 1.0 - ARMOR_RED[min(armor, 4)])
    return count * hp * dmg * mult * tech


def army_power(army: dict[str, int], opponents: dict[str, int], weapon: int = 0, armor: int = 0) -> float:
    return sum(unit_power(t, n, opponents, weapon, armor) for t, n in army.items() if t in COMBAT)


def power_ratio(f: dict, req=None) -> float | None:
    """Own / visible enemy power; None when no enemy army is visible (enemy strength unknown)."""
    own = req.own_power if req is not None and req.own_power >= 0 else army_power(f["army"], f["enemy_units"], f["weapon"], f["armor"])
    enemy_army = {t: n for t, n in f["enemy_units"].items() if t in COMBAT}
    if req is not None and req.enemy_power >= 0:
        enemy = req.enemy_power
    else:
        enemy = army_power(enemy_army, f["army"])
    if enemy <= 0:
        return None
    return own / enemy


# ---------------------------------------------------------------------------------------------- candidates (hard constraints)
def _affordable(f: dict, option: str) -> bool:
    w, fo, g = COSTS[option]
    return f["wood"] >= w and f["food"] >= fo and f["gold"] >= g


def candidate_units(f: dict, allowed: Iterable[str] | None = None) -> list[str]:
    """Units the validator would accept now (building, resources, population). Others are never offered to Laya."""
    if f["free_pop"] <= 0:
        return []
    out = []
    for u in UNITS:
        needs = {"worker": f["town_center"] > 0, "spearman": f["barracks_ready"], "archer": f["barracks_ready"],
                 "cavalry": f["stable_ready"]}[u]
        if needs and _affordable(f, u):
            out.append(u)
    if allowed is not None:
        allowed = set(allowed)
        out = [u for u in out if u in allowed]
    return out


def candidate_builds(f: dict, cfg: BotConfig, allowed: Iterable[str] | None = None) -> list[str]:
    """Buildings the bot can afford and is allowed to add now ("none" is always possible)."""
    rules = {
        "house": True,
        "farm": True,
        "mine": f["mine"] < 3,
        "barracks": f["barracks"] == 0,
        "stable": f["barracks_ready"] and f["stable"] == 0,
        "tower": f["tower"] < cfg.max_towers,
        "wall": f["wall"] == 0 and f["workers"] >= 10,
    }
    out = ["none"] + [b for b in BUILDS[1:] if rules[b] and _affordable(f, b)]
    if allowed is not None:
        allowed = set(allowed) | {"none"}
        out = [b for b in out if b in allowed]
    return out


# ---------------------------------------------------------------------------------------------- utilities
def _normalize(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in scores.values())
    if total <= 0:
        return {k: 1.0 / len(scores) for k in scores} if scores else {}
    return {k: max(0.0, v) / total for k, v in scores.items()}


def threat_label(f: dict, ratio: float | None) -> str:
    if f["attacks"] >= 2 or (ratio is not None and ratio < 0.8):
        return "high"
    if f["enemy_n"] > 0 or f["attacks"] >= 1:
        return "medium"
    return "low"


def heuristic(req, cfg: BotConfig | None = None, allowed_units=None, allowed_build=None, zones: list[str] | None = None) -> dict:
    """Utility distribution per question: {qid: {label: p}} (+ "attack_now": {"yes": p, "no": 1-p})."""
    cfg = cfg or BotConfig()
    f = facts(req)
    ratio = power_ratio(f, req)
    threat = threat_label(f, ratio)
    army_ok = f["army_n"] >= cfg.min_army
    attack_ok = army_ok and ratio is not None and ratio >= cfg.attack_ratio
    out: dict[str, dict[str, float]] = {}

    # strategy
    s = {"economy": 1.0, "defend": 0.3, "attack": 0.05, "tech": 0.1}
    if f["workers"] < 10:
        s["economy"] += 2.0
    if threat == "high":
        s["defend"] += 2.5
    elif threat == "medium":
        s["defend"] += 1.0
    if attack_ok:
        s["attack"] += 3.0
    elif ratio is None and f["army_n"] >= cfg.min_army + 2:
        s["attack"] += 1.2          # strength unknown: cautious, the rule layer scouts first
    if f["blacksmith"] > 0 and f["workers"] >= 10 and f["gold"] >= 100 and threat == "low":
        s["tech"] += 1.5
    out["strategy"] = _normalize(s)

    # next_unit (only feasible candidates)
    units = candidate_units(f, allowed_units)
    if units:
        u = {k: 0.2 for k in units}
        if "worker" in u:
            u["worker"] += 3.0 if f["workers"] < 8 else (1.0 if f["workers"] < 14 and threat == "low" else 0.0)
        counter = {"Cavalry": "spearman", "Archer": "cavalry", "Spearman": "archer"}.get(f["dominant_enemy"], "")
        if counter in u:
            u[counter] += 3.0 if f["workers"] >= 6 or threat != "low" else 1.0
        if not counter:
            # no visible enemy: balanced army (spearman/archer alternate)
            if "spearman" in u and f["army"]["Spearman"] <= f["army"]["Archer"]:
                u["spearman"] += 1.0
            elif "archer" in u:
                u["archer"] += 1.0
        if f["plagues"] or f["units_lost"] >= 2:      # replace losses
            for k in u:
                u[k] += 0.3
        out["next_unit"] = _normalize(u)

    # threat_level
    out["threat_level"] = {k: (0.7 if k == threat else 0.15) for k in THREATS}

    # attack_now
    p_attack = 0.85 if attack_ok else 0.1
    out["attack_now"] = {"yes": p_attack, "no": 1.0 - p_attack}

    # target_zone (largest visible group first)
    if zones:
        totals = {z: 0 for z in zones}
        for e in req.visible_enemies:
            if e.region in totals:
                totals[e.region] += e.count
        out["target_zone"] = _normalize({z: n + 0.5 for z, n in totals.items()})

    # build_next (only feasible candidates)
    builds = candidate_builds(f, cfg, allowed_build)
    b = {k: 0.0 for k in builds}
    b["none"] = 0.6
    if "house" in b and f["free_pop"] <= 3:
        b["house"] += 3.0
    if "farm" in b and (f["food"] < 150 or f["fires"]) and f["farm"] < 8:
        b["farm"] += 2.6
    if "mine" in b and f["gold"] < 100 and f["workers"] >= 6:
        b["mine"] += 2.3
    if "barracks" in b and f["workers"] >= 6:
        b["barracks"] += 2.7
    if "stable" in b and f["workers"] >= 12:
        b["stable"] += 1.4
    if "tower" in b and (f["attacks"] >= 2 or threat == "high"):
        b["tower"] += 3.2
    if "wall" in b and (f["attacks"] >= 1 or f["enemy_seen"]) and f["workers"] >= 12:
        b["wall"] += 1.3
    for lost in f["lost_buildings"]:           # rebuild what fire / attacks destroyed
        key = {"House": "house", "Barracks": "barracks", "Stable": "stable", "Mine": "mine", "DefenseTower": "tower"}.get(lost)
        if key in b:
            b[key] += 3.5
    out["build_next"] = _normalize(b)

    # economy_focus: lowest relative stock; plague / losses push food (retraining), fire pushes the most burned
    e = {"food": 1.0 / (1 + f["food"] / 100.0), "wood": 1.0 / (1 + f["wood"] / 100.0), "gold": 0.6 / (1 + f["gold"] / 100.0)}
    if f["plagues"] or f["units_lost"] >= 2:
        e["food"] += 0.6
    out["economy_focus"] = _normalize(e)
    out["_meta"] = {"ratio": ratio, "threat": threat, "attack_ok": attack_ok, "units": units, "builds": builds}
    return out


def argmax(dist: dict[str, float]) -> str:
    """Highest probability; ties broken by the option order given in the dict (deterministic)."""
    best, best_p = "", -1.0
    for k, v in dist.items():
        if v > best_p + 1e-12:
            best, best_p = k, v
    return best


def blend(laya: dict[str, float] | None, heur: dict[str, float], w: float) -> dict[str, float]:
    """final = w * Laya + (1 - w) * heuristic over the heuristic's (feasible) options; w = 0 without Laya."""
    if not laya or w <= 0:
        return dict(heur)
    keys = list(heur.keys())
    lsum = sum(max(0.0, laya.get(k, 0.0)) for k in keys)
    lnorm = {k: (max(0.0, laya.get(k, 0.0)) / lsum if lsum > 0 else 1.0 / len(keys)) for k in keys}
    return {k: w * lnorm[k] + (1.0 - w) * heur[k] for k in keys}
