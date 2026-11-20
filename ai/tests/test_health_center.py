"""Health Center (Medieval) / Med Bay (Sci-Fi) integration: Unity snapshot contract, MCP tools, ActionPlan schema,
LLM name localization, guard, RAG and the VsAI bot's Laya decision layer (heuristic + options + state template)."""

import asyncio
import json
import unittest

from mcp import Client

from agent import guard
from agent.agent_runner import _glossary, localize_names
from agent.plan_validation import build_plan, precheck_actions, validate_plan
from decision import bot_decider
from decision import bot_heuristic as H
from decision.bot_config import BotConfig
from mcp_server import catalog
from mcp_server.server import build_server
from mcp_server.session import SafeSnapshot
from rag.retriever import KnowledgeIndex
from tests.helpers import context, snapshot

INDEX = KnowledgeIndex.load()

# Exactly what Unity's JsonUtility writes after this change: AiUnitGroup has wounded / healing, HealthCenter is a building.
UNITY_JSON = """{"match_id":"Room_1","game_mode":"Medieval","ui_language":"tr","game_time_seconds":300.0,
"map_size":{"x":64,"y":64},"base_region":"SouthWest","resources":{"wood":300,"food":200,"gold":120},
"population":{"current":12,"max":25,"queued":0},
"own_units":[{"type":"Worker","display_name":"Worker","count":6,"region":"SouthWest","idle":1,"wounded":0,"healing":0},
             {"type":"Spearman","display_name":"Spearman","count":5,"region":"South","idle":2,"wounded":2,"healing":1}],
"own_buildings":[{"type":"TownCenter","display_name":"Town Center","count":1,"under_construction":0,"queued_units":0,"region":"SouthWest"},
                 {"type":"HealthCenter","display_name":"Health Center","count":1,"under_construction":0,"queued_units":0,"region":"SouthWest"}],
"visible_enemies":[],"visible_enemy_buildings":[{"type":"HealthCenter","display_name":"Med Bay","count":1,"region":"North"}],
"tech":{"weapon_level":0,"armor_level":0,"wall_level":0,"researching":"","research_progress":0.0,"researched":[]},
"recent_events":[]}"""


def call(tool, args, snap: SafeSnapshot):
    async def go():
        ctx = context()
        ctx.snapshot = snap
        async with Client(build_server(ctx, INDEX)) as c:
            r = await c.call_tool(tool, args)
            return r.is_error, r.structured_content
    return asyncio.run(go())


def bot_req(**overrides):
    body = {"match_id": "t", "resources": {"wood": 200, "food": 200, "gold": 100}, "population": {"current": 13, "max": 25},
            "own_units": [{"type": "Worker", "count": 8}, {"type": "Spearman", "count": 3}, {"type": "Archer", "count": 2}],
            "own_buildings": [{"type": "TownCenter", "count": 1}, {"type": "Barracks", "count": 1}], "combat_units": 5}
    body.update(overrides)
    return bot_decider.BotDecideRequest.model_validate(body)


class SnapshotAndToolTests(unittest.TestCase):
    def test_unity_snapshot_with_health_center_and_wounded_counts_validates(self):
        snap = SafeSnapshot.model_validate(json.loads(UNITY_JSON))
        self.assertEqual(snap.own_buildings[1].type, "HealthCenter")
        self.assertEqual(snap.own_units[1].wounded, 2)
        self.assertEqual(snap.own_units[1].healing, 1)

    def test_old_unity_snapshot_without_new_fields_still_validates(self):
        data = json.loads(UNITY_JSON)
        for u in data["own_units"]:
            u.pop("wounded"), u.pop("healing")
        self.assertEqual(SafeSnapshot.model_validate(data).own_units[1].wounded, 0)

    def test_army_status_reports_wounded_healing_and_ready_centers(self):
        err, data = call("get_army_status", {}, SafeSnapshot.model_validate(json.loads(UNITY_JSON)))
        self.assertFalse(err)
        self.assertEqual(data["wounded_total"], 2)
        self.assertEqual(data["healing_total"], 1)
        self.assertEqual(data["health_centers_ready"], 1)

    def test_cost_estimate_knows_the_health_center(self):
        err, data = call("estimate_plan_cost", {"items": [{"kind": "building", "id": "HealthCenter", "count": 1}]}, snapshot())
        self.assertFalse(err, data)
        self.assertEqual(catalog.cost_of("building", "HealthCenter"), {"wood": 100, "food": 0, "gold": 50})


class CatalogPlanAndNamingTests(unittest.TestCase):
    def test_aliases_in_both_modes_and_languages(self):
        for name in ("Health Center", "health centre", "Med Bay", "medbay", "Sağlık Merkezi", "revir", "hastane", "şifahane"):
            self.assertEqual(catalog.canonical_building(name), "HealthCenter", name)
        self.assertEqual(catalog.canonical_target("Med Bay"), "HealthCenter")
        self.assertEqual(catalog.display_name("building", "HealthCenter", "SciFi"), "Med Bay")
        self.assertEqual(catalog.display_name("building", "HealthCenter", "Medieval"), "Health Center")

    def test_build_and_attack_actions_accept_health_center(self):
        plan, rejected = build_plan("Heal", 0.8, [
            {"action_type": "BUILD", "building_type": "Med Bay", "reason": "heal wounded units"},
            {"action_type": "ATTACK", "target_zone": "North", "target_type": "health center", "count": 3, "reason": "r"},
        ])
        self.assertEqual(rejected, [])
        self.assertEqual(plan["actions"][0]["building_type"], "HealthCenter")
        self.assertEqual(plan["actions"][1]["target_type"], "HealthCenter")
        self.assertEqual(validate_plan(plan), [])

    def test_precheck_charges_the_health_center_cost(self):
        snap = SafeSnapshot.model_validate(json.loads(UNITY_JSON))
        poor = snap.model_copy(update={"resources": snap.resources.model_copy(update={"gold": 10})})
        build = [{"action_type": "BUILD", "building_type": "HealthCenter", "reason": "r"}]
        self.assertEqual(precheck_actions(build, snap), [""])
        self.assertIn("gold", precheck_actions(build, poor)[0])

    def test_turkish_answer_names_and_glossary(self):
        self.assertEqual(localize_names("Build a Health Center.", "Medieval", "tr"), "Build a Sağlık Merkezi.")
        self.assertEqual(localize_names("Build a Med Bay.", "SciFi", "tr"), "Build a Revir.")
        self.assertIn("HealthCenter = Med Bay", _glossary("SciFi", "en"))

    def test_guard_blocks_opponent_health_center_intel_but_allows_rules(self):
        for q in ("Rakibin sağlık merkezi var mı?", "does the enemy have a health center", "did the opponent build a med bay"):
            self.assertTrue(guard.precheck(q)["cheat"], q)
        for q in ("Sağlık merkezi ne işe yarar?", "How do I heal my wounded units?", "Should I build a Med Bay?"):
            self.assertFalse(guard.precheck(q)["cheat"], q)


class RagTests(unittest.TestCase):
    def test_turkish_and_english_questions_find_the_health_center_records(self):
        for q in ("how do I heal wounded units", "yaralı birimlerimi nasıl iyileştiririm", "revir ne kadar", "Med Bay cost"):
            ids = [h["source_id"] for h in INDEX.search(q, 3)]
            self.assertEqual(ids[0], "building_healthcenter_v1", (q, ids))

    def test_town_center_question_still_ranks_the_town_center_first(self):
        self.assertEqual(INDEX.search("şehir merkezi ne işe yarar", 1)[0]["source_id"], "building_towncenter_v1")


class BotDecisionTests(unittest.TestCase):
    def test_wounded_army_with_barracks_builds_a_health_center(self):
        r = bot_req(wounded_units=3)
        self.assertEqual(H.argmax(H.heuristic(r)["build_next"]), "health_center")

    def test_no_health_center_without_a_ready_barracks_or_when_one_exists(self):
        no_barracks = bot_req(wounded_units=3, own_buildings=[{"type": "TownCenter", "count": 1}])
        self.assertNotIn("health_center", H.candidate_builds(H.facts(no_barracks), BotConfig()))
        pending = bot_req(wounded_units=3, own_buildings=[{"type": "TownCenter", "count": 1},
                                                          {"type": "Barracks", "count": 1, "under_construction": 1}])
        self.assertNotIn("health_center", H.candidate_builds(H.facts(pending), BotConfig()))
        exists = bot_req(wounded_units=3, own_buildings=[{"type": "TownCenter", "count": 1}, {"type": "Barracks", "count": 1},
                                                         {"type": "HealthCenter", "count": 1}])
        self.assertNotIn("health_center", H.candidate_builds(H.facts(exists), BotConfig()))

    def test_unaffordable_or_not_allowed_health_center_is_never_offered(self):
        poor = bot_req(wounded_units=3, resources={"wood": 200, "food": 200, "gold": 40})
        self.assertNotIn("health_center", H.candidate_builds(H.facts(poor), BotConfig()))
        blocked = bot_req(wounded_units=3, allowed_build=["none", "house"])
        self.assertNotIn("health_center", H.candidate_builds(H.facts(blocked), BotConfig(), blocked.allowed_build))

    def test_healthy_army_without_attacks_does_not_prioritise_it(self):
        self.assertNotEqual(H.argmax(H.heuristic(bot_req(wounded_units=0))["build_next"]), "health_center")

    def test_lost_health_center_is_rebuilt(self):
        r = bot_req(own_buildings=[{"type": "TownCenter", "count": 1}, {"type": "Barracks", "count": 1}],
                    recent_events=[{"type": "BUILDING_LOST", "detail": "HealthCenter", "seconds_ago": 5}])
        self.assertEqual(H.argmax(H.heuristic(r)["build_next"]), "health_center")

    def test_laya_question_and_state_include_the_health_center(self):
        r = bot_req(wounded_units=3)
        q = bot_decider.build_questions(r)
        self.assertIn("health_center", q["build_next"]["criteria"])
        self.assertIn("30% HP", q["build_next"]["criteria"]["health_center"])
        state = bot_decider.build_state(r)
        self.assertIn("wounded 3", state)
        self.assertIn("health center 0", state)


if __name__ == "__main__":
    unittest.main()
