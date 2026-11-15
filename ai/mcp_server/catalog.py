"""Game catalog (costs, producers, upgrade tiers) loaded from the same knowledge files used by RAG.

Used by deterministic tools (estimate_plan_cost, get_technology_status) and by the ActionPlan validator so that
costs are computed in code, not guessed by the LLM. Values mirror the Unity ScriptableObjects / UpgradeCatalog.cs.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "rag" / "knowledge"

UNIT_TYPES = ("Worker", "Spearman", "Archer", "Cavalry")
BUILDABLE_TYPES = ("House", "Barracks", "Stable", "Blacksmith", "Mine", "DefenseTower")
TECH_LINES = ("weapon", "armor", "wall")
REGIONS = ("NorthWest", "North", "NorthEast", "West", "Center", "East", "SouthWest", "South", "SouthEast")

# Display names (both modes, English + Turkish) -> canonical ids. Lower-cased, ASCII folded keys.
_UNIT_ALIASES = {
    "worker": "Worker", "engineer": "Worker", "villager": "Worker", "isci": "Worker", "muhendis": "Worker",
    "spearman": "Spearman", "spearmen": "Spearman", "marine": "Spearman", "mizrakci": "Spearman", "piyade": "Spearman",
    "archer": "Archer", "sniper": "Archer", "okcu": "Archer", "keskin nisanci": "Archer",
    "cavalry": "Cavalry", "tank": "Cavalry", "knight": "Cavalry", "suvari": "Cavalry",
}
_BUILDING_ALIASES = {
    "house": "House", "habitat": "House", "ev": "House",
    "barracks": "Barracks", "armory": "Barracks", "kisla": "Barracks",
    "stable": "Stable", "vehicle bay": "Stable", "vehiclebay": "Stable", "ahir": "Stable",
    "blacksmith": "Blacksmith", "tech lab": "Blacksmith", "techlab": "Blacksmith", "demirci": "Blacksmith",
    "mine": "Mine", "gold mine": "Mine", "gold refinery": "Mine", "maden": "Mine",
    "defensetower": "DefenseTower", "defense tower": "DefenseTower", "tower": "DefenseTower",
    "archer tower": "DefenseTower", "rocket turret": "DefenseTower", "kule": "DefenseTower",
}
_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u"})


def _key(name: str) -> str:
    return " ".join((name or "").replace("İ", "i").lower().translate(_FOLD).replace("_", " ").split())


def canonical_unit(name: str) -> str | None:
    k = _key(name)
    if k in _UNIT_ALIASES:
        return _UNIT_ALIASES[k]
    if k.endswith("s") and k[:-1] in _UNIT_ALIASES:  # "archers", "tanks"
        return _UNIT_ALIASES[k[:-1]]
    return None


def canonical_building(name: str) -> str | None:
    k = _key(name)
    return _BUILDING_ALIASES.get(k) or _BUILDING_ALIASES.get(k.replace(" ", ""))


def canonical_region(name: str) -> str | None:
    k = _key(name).replace(" ", "").replace("-", "")
    for r in REGIONS:
        if r.lower() == k:
            return r
    aliases = {"northgate": "North", "southgate": "South", "eastgate": "East", "westgate": "West",
               "kuzey": "North", "guney": "South", "dogu": "East", "bati": "West", "merkez": "Center", "middle": "Center",
               "kuzeybati": "NorthWest", "kuzeydogu": "NorthEast", "guneybati": "SouthWest", "guneydogu": "SouthEast"}
    return aliases.get(k)


@lru_cache(maxsize=1)
def _load(name: str) -> tuple:
    return tuple(json.loads((KNOWLEDGE_DIR / name).read_text(encoding="utf-8")))


def unit_record(unit: str) -> dict:
    return next(r for r in _load("units.json") if r["name"] == unit)


def building_record(building: str) -> dict:
    return next(r for r in _load("buildings.json") if r["name"] == building)


def tech_record(line: str, level: int) -> dict | None:
    return next((r for r in _load("technologies.json") if r["line"] == line and r["level"] == level), None)


def max_level(line: str) -> int:
    return max(r["level"] for r in _load("technologies.json") if r["line"] == line)


def producer_of(unit: str) -> str:
    return unit_record(unit)["trained_at"]


def display_name(kind: str, canonical: str, game_mode: str) -> str:
    rec = unit_record(canonical) if kind == "unit" else building_record(canonical)
    if game_mode == "SciFi":
        return rec.get("scifi_name") or rec.get("display_name") or canonical
    return rec.get("display_name") or canonical


def cost_of(kind: str, ident: str, count: int = 1, tech_levels: dict | None = None) -> dict:
    """Returns total {"wood","food","gold"} for `count` items. For techs `ident` is a line name (next tier)."""
    if kind == "unit":
        cost = unit_record(ident)["cost"]
    elif kind == "building":
        cost = building_record(ident)["cost"]
    elif kind == "tech":
        level = (tech_levels or {}).get(ident, 0) + 1
        rec = tech_record(ident, level)
        if rec is None:
            raise ValueError(f"{ident} upgrades are already at the maximum tier")
        cost, count = rec["cost"], 1
    else:
        raise ValueError(f"unknown kind {kind}")
    return {res: int(cost.get(res, 0)) * count for res in ("wood", "food", "gold")}
