"""Hand-written bot decision scenarios (evaluation only — NEVER used as fine-tune training data).

Each scenario: a /bot/decide request (bot's own state + what it can see) and the answers a sensible RTS player would
accept per question (a set; several answers can be fine). Expectations come from the game rules (counter triangle,
costs, population cap, disaster rules), not from the heuristic's output.
"""

from __future__ import annotations

import copy

BASE = {
    "match_id": "eval", "game_mode": "Medieval", "game_time_seconds": 400.0,
    "resources": {"wood": 200, "food": 200, "gold": 100}, "population": {"current": 12, "max": 25},
    "combat_units": 0, "idle_workers": 0, "weapon_level": 0, "armor_level": 0,
    "own_units": [{"type": "Worker", "count": 10}],
    "own_buildings": [{"type": "TownCenter", "count": 1, "under_construction": 0},
                      {"type": "Barracks", "count": 1, "under_construction": 0}],
    "researched": [], "visible_enemies": [], "recent_events": [],
}


def req(**o) -> dict:
    r = copy.deepcopy(BASE)
    for k, v in o.items():
        r[k] = v
    army = sum(u["count"] for u in r["own_units"] if u["type"] != "Worker")
    r["combat_units"] = army
    return r


def units(workers=10, spear=0, archer=0, cav=0):
    return [{"type": "Worker", "count": workers}, {"type": "Spearman", "count": spear},
            {"type": "Archer", "count": archer}, {"type": "Cavalry", "count": cav}]


def bld(*extra, barracks=True, stable=False):
    b = [{"type": "TownCenter", "count": 1, "under_construction": 0}]
    if barracks:
        b.append({"type": "Barracks", "count": 1, "under_construction": 0})
    if stable:
        b.append({"type": "Stable", "count": 1, "under_construction": 0})
    for t, n in extra:
        b.append({"type": t, "count": n, "under_construction": 0})
    return b


def enemy(t, n, z="West"):
    return {"type": t, "count": n, "region": z}


def ev(t, z="West", ago=15.0, detail=""):
    return {"type": t, "region": z, "seconds_ago": ago, "detail": detail}


SCENARIOS = [
    # ---------------------------------------------------------------- counters (next_unit)
    ("cav8_vs_2spear", req(own_units=units(10, spear=2), visible_enemies=[enemy("Cavalry", 8)]),
     {"next_unit": {"spearman"}, "threat_level": {"high"}, "attack_now": {"no"}}),
    ("archers_massing", req(own_units=units(12, spear=3), resources={"wood": 300, "food": 400, "gold": 200},
                            own_buildings=bld(stable=True), visible_enemies=[enemy("Archer", 7, "North")]),
     {"next_unit": {"cavalry"}, "attack_now": {"no"}}),
    ("spear_blob", req(own_units=units(12, cav=2), resources={"wood": 300, "food": 300, "gold": 100},
                       visible_enemies=[enemy("Spearman", 6, "East")]),
     {"next_unit": {"archer"}}),
    ("cav_raid_small", req(own_units=units(12, spear=1, archer=1), visible_enemies=[enemy("Cavalry", 3, "South")]),
     {"next_unit": {"spearman"}}),
    ("mixed_mostly_cav", req(own_units=units(12, archer=2), visible_enemies=[enemy("Cavalry", 5), enemy("Archer", 2)]),
     {"next_unit": {"spearman"}}),
    ("scifi_tanks", req(game_mode="SciFi", own_units=units(12, spear=1), visible_enemies=[enemy("Cavalry", 6, "NorthEast")]),
     {"next_unit": {"spearman"}}),
    ("no_barracks_cav", req(own_buildings=bld(barracks=False), own_units=units(10), visible_enemies=[enemy("Cavalry", 4)]),
     {"build_next": {"barracks", "tower"}}),
    # ---------------------------------------------------------------- economy
    ("early_workers", req(own_units=units(4), own_buildings=bld(barracks=False), population={"current": 4, "max": 25}),
     {"strategy": {"economy"}, "next_unit": {"worker"}}),
    ("few_workers_mid", req(own_units=units(6, spear=2), population={"current": 8, "max": 25}),
     {"next_unit": {"worker"}, "strategy": {"economy"}}),
    ("food_very_low", req(resources={"wood": 200, "food": 30, "gold": 100}),
     {"build_next": {"farm"}, "economy_focus": {"food"}}),
    ("food_low_wood_rich", req(resources={"wood": 400, "food": 60, "gold": 150}),
     {"build_next": {"farm"}, "economy_focus": {"food"}}),
    ("gold_low", req(resources={"wood": 300, "food": 300, "gold": 80}),
     {"build_next": {"mine"}, "economy_focus": {"gold"}}),
    ("gold_low_two_mines", req(resources={"wood": 300, "food": 300, "gold": 85}, own_buildings=bld(("Mine", 1))),
     {"build_next": {"mine"}, "economy_focus": {"gold"}}),
    ("wood_low", req(resources={"wood": 20, "food": 300, "gold": 200}),
     {"economy_focus": {"wood"}}),
    ("pop_cap_reached", req(population={"current": 24, "max": 25}),
     {"build_next": {"house"}}),
    ("pop_cap_full", req(population={"current": 25, "max": 25}, resources={"wood": 150, "food": 200, "gold": 100}),
     {"build_next": {"house"}}),
    ("rich_no_need", req(resources={"wood": 500, "food": 500, "gold": 50}, own_units=units(14, spear=3, archer=3),
                         own_buildings=bld(("Farm", 6), ("Mine", 3), stable=True), population={"current": 20, "max": 30}),
     {"build_next": {"none", "wall"}}),
    # ---------------------------------------------------------------- threat & defense
    ("repeated_attacks", req(resources={"wood": 100, "food": 300, "gold": 150},
                             recent_events=[ev("UNDER_ATTACK", ago=10), ev("UNDER_ATTACK", ago=40)]),
     {"build_next": {"tower"}, "threat_level": {"high"}, "strategy": {"defend"}}),
    ("attacks_no_tower_yet", req(resources={"wood": 50, "food": 200, "gold": 120}, own_units=units(10, spear=2),
                                 recent_events=[ev("UNDER_ATTACK", "North", 5), ev("UNDER_ATTACK", "North", 25)]),
     {"build_next": {"tower"}, "strategy": {"defend"}}),
    ("tower_cap", req(resources={"wood": 50, "food": 200, "gold": 300}, own_buildings=bld(("DefenseTower", 3)),
                      recent_events=[ev("UNDER_ATTACK", ago=10), ev("UNDER_ATTACK", ago=30)]),
     {"build_next": {"none", "farm", "house", "mine"}}),
    ("single_attack", req(own_units=units(12, spear=2), recent_events=[ev("UNDER_ATTACK", ago=20)]),
     {"threat_level": {"medium", "high"}}),
    ("big_enemy_army", req(own_units=units(10, spear=3), visible_enemies=[enemy("Spearman", 6), enemy("Archer", 6)]),
     {"threat_level": {"high"}, "strategy": {"defend"}, "attack_now": {"no"}}),
    ("enemy_seen_wall", req(own_units=units(14, spear=2), resources={"wood": 300, "food": 300, "gold": 40},
                            own_buildings=bld(("Farm", 8), ("Mine", 3), stable=True), population={"current": 16, "max": 30},
                            visible_enemies=[enemy("Worker", 1, "North")]),
     {"build_next": {"wall"}}),
    ("calm_low_threat", req(own_units=units(12, spear=2, archer=2)),
     {"threat_level": {"low"}, "attack_now": {"no"}}),
    # ---------------------------------------------------------------- attack decisions (power comparison)
    ("strong_vs_archers", req(own_units=units(12, cav=10), own_buildings=bld(stable=True), population={"current": 22, "max": 30},
                              visible_enemies=[enemy("Archer", 4, "North")]),
     {"strategy": {"attack"}, "attack_now": {"yes"}}),
    ("strong_spears_vs_cav", req(own_units=units(12, spear=12), population={"current": 24, "max": 30},
                                 visible_enemies=[enemy("Cavalry", 4, "East")]),
     {"strategy": {"attack"}, "attack_now": {"yes"}}),
    ("weak_vs_counter", req(own_units=units(12, spear=5), visible_enemies=[enemy("Archer", 6, "South")]),
     {"attack_now": {"no"}}),
    ("army_but_fog", req(own_units=units(12, spear=4, archer=4), population={"current": 20, "max": 30}),
     {"attack_now": {"no"}}),
    ("tiny_army_strong_ratio", req(own_units=units(10, cav=2), own_buildings=bld(stable=True), visible_enemies=[enemy("Archer", 1)]),
     {"attack_now": {"no"}}),
    ("even_fight", req(own_units=units(12, spear=4, archer=4), visible_enemies=[enemy("Spearman", 4), enemy("Archer", 4)]),
     {"attack_now": {"no"}}),
    # ---------------------------------------------------------------- disasters
    ("fire_lost_barracks", req(own_units=units(8), own_buildings=bld(barracks=False),
                               recent_events=[ev("FIRE", "SouthWest", 20, "Barracks"), ev("BUILDING_LOST", "SouthWest", 5, "Barracks")]),
     {"build_next": {"barracks"}}),
    ("fire_lost_house_cap", req(population={"current": 23, "max": 25},
                                recent_events=[ev("FIRE", "SouthWest", 30, "House"), ev("BUILDING_LOST", "SouthWest", 10, "House")]),
     {"build_next": {"house"}}),
    ("fire_burned_food", req(resources={"wood": 150, "food": 90, "gold": 80},
                             recent_events=[ev("FIRE", "SouthWest", 10, "TownCenter")]),
     {"build_next": {"farm", "mine"}, "economy_focus": {"food", "gold"}}),
    ("plague_losses", req(own_units=units(7, spear=1), resources={"wood": 200, "food": 200, "gold": 100},
                          recent_events=[ev("PLAGUE", ago=15), ev("UNIT_LOST", ago=10), ev("UNIT_LOST", ago=5)]),
     {"next_unit": {"worker"}, "economy_focus": {"food"}}),
    # ---------------------------------------------------------------- tech
    ("tech_ready", req(own_units=units(12, spear=4), resources={"wood": 300, "food": 300, "gold": 300},
                       own_buildings=bld(("Blacksmith", 1))),
     {"strategy": {"tech", "economy"}}),
]
