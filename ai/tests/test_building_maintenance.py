"""Building repair / demolish (BuildingMaintenanceRules.cs) and fire damage integration on the AI side:
Unity snapshot contract, MCP get_army_status, ActionPlan schema (REPAIR / DEMOLISH), Commander answer schema and prompt,
plan pre-check, RAG, and the VsAI bot's Laya decision layer (maintenance question + heuristic + state + RAG)."""

import asyncio
import json
import unittest

from mcp import Client

from agent.agent_runner import ANSWER_SYSTEM, ROUTER_SYSTEM, StrategicCommander, _answer_schema
from agent.logging_utils import AgentLogger
from agent.plan_validation import build_plan, normalize_action, precheck_actions, validate_plan
from decision import bot_decider, bot_rag
from decision import bot_heuristic as H
from decision.bot_config import BotConfig
from mcp_server import catalog
from mcp_server.server import ALL_TOOLS, build_server
from mcp_server.session import SafeSnapshot
from rag.retriever import KnowledgeIndex
from tests.helpers import FakeLLM, context

INDEX = KnowledgeIndex.load()

# Exactly what Unity's JsonUtility writes after this change: AiBuildingGroup has damaged / repairing / demolishing /
# min_hp_pct / repair_cost (AiSafeSnapshot.cs).
UNITY_JSON = """{"match_id":"Room_1","game_mode":"Medieval","ui_language":"tr","game_time_seconds":420.0,
"map_size":{"x":64,"y":64},"base_region":"SouthWest","resources":{"wood":120,"food":200,"gold":60},
"population":{"current":12,"max":25,"queued":0},
"own_units":[{"type":"Worker","display_name":"Worker","count":6,"region":"SouthWest","idle":1,"wounded":0,"healing":0},
             {"type":"Spearman","display_name":"Spearman","count":5,"region":"South","idle":2,"wounded":0,"healing":0}],
"own_buildings":[{"type":"TownCenter","display_name":"Town Center","count":1,"under_construction":0,"queued_units":0,"region":"SouthWest",
                  "damaged":1,"repairing":0,"demolishing":0,"min_hp_pct":40,"repair_cost":{"wood":60,"food":0,"gold":15}},
                 {"type":"Barracks","display_name":"Barracks","count":2,"under_construction":0,"queued_units":0,"region":"SouthWest",
                  "damaged":0,"repairing":1,"demolishing":0,"min_hp_pct":70,"repair_cost":{"wood":0,"food":0,"gold":0}},
                 {"type":"House","display_name":"House","count":2,"under_construction":0,"queued_units":0,"region":"SouthWest",
                  "damaged":0,"repairing":0,"demolishing":0,"min_hp_pct":100,"repair_cost":{"wood":0,"food":0,"gold":0}}],
"visible_enemies":[],"visible_enemy_buildings":[],
"tech":{"weapon_level":0,"armor_level":0,"wall_level":0,"researching":"","research_progress":0.0,"researched":[]},
"recent_events":[{"type":"DISASTER","detail":"Fire at TownCenter","region":"SouthWest","seconds_ago":20.0}]}"""


def snap() -> SafeSnapshot:
    return SafeSnapshot.model_validate(json.loads(UNITY_JSON))


def call(tool, args, s: SafeSnapshot):
    async def go():
        ctx = context()
        ctx.snapshot = s
        async with Client(build_server(ctx, INDEX)) as c:
            r = await c.call_tool(tool, args)
            return r.is_error, r.structured_content
    return asyncio.run(go())


def bot_req(**overrides):
    body = {"match_id": "t", "resources": {"wood": 300, "food": 300, "gold": 150}, "population": {"current": 16, "max": 30},
            "own_units": [{"type": "Worker", "count": 10}, {"type": "Spearman", "count": 4}, {"type": "Archer", "count": 2}],
            "own_buildings": [{"type": "TownCenter", "count": 1}, {"type": "Barracks", "count": 1}], "combat_units": 6}
    body.update(overrides)
    return bot_decider.BotDecideRequest.model_validate(body)


ATTACKS = [{"type": "UNDER_ATTACK", "region": "West", "seconds_ago": 8}, {"type": "UNDER_ATTACK", "region": "West", "seconds_ago": 30}]


class SnapshotAndToolTests(unittest.TestCase):
    def test_unity_snapshot_with_maintenance_fields_validates(self):
        s = snap()
        tc = s.own_buildings[0]
        self.assertEqual((tc.damaged, tc.min_hp_pct, tc.repair_cost.wood, tc.repair_cost.gold), (1, 40, 60, 15))
        self.assertEqual(s.own_buildings[1].repairing, 1)

    def test_old_unity_snapshot_without_maintenance_fields_still_validates(self):
        data = json.loads(UNITY_JSON)
        for b in data["own_buildings"]:
            for k in ("damaged", "repairing", "demolishing", "min_hp_pct", "repair_cost"):
                b.pop(k)
        b = SafeSnapshot.model_validate(data).own_buildings[0]
        self.assertEqual((b.damaged, b.min_hp_pct, b.repair_cost.wood), (0, 100, 0))

    def test_bad_maintenance_values_are_rejected(self):
        for field, value in (("min_hp_pct", 150), ("damaged", -1), ("repair_cost", {"wood": 1, "food": 0, "gold": 0, "x": 1})):
            data = json.loads(UNITY_JSON)
            data["own_buildings"][0][field] = value
            with self.assertRaises(Exception, msg=field):
                SafeSnapshot.model_validate(data)

    def test_army_status_lists_damaged_buildings_with_repair_costs(self):
        err, data = call("get_army_status", {}, snap())
        self.assertFalse(err, data)
        self.assertEqual(data["damaged_buildings"], [{"type": "TownCenter", "display_name": "Town Center", "damaged": 1,
                                                      "lowest_hp_pct": 40, "repair_cost": {"wood": 60, "food": 0, "gold": 15}}])
        self.assertEqual(data["maintenance_in_progress"], [{"type": "Barracks", "repairing": 1, "demolishing": 0}])
        self.assertIn("never the Town Center", data["maintenance_rules"])
        self.assertIn("50%", data["maintenance_rules"])

    def test_no_new_tool_was_added(self):
        # Repair / demolish is reported by the existing read-only tool; actions stay in the ActionPlan (never a tool)
        self.assertEqual(len(ALL_TOOLS), 7)


class PlanSchemaTests(unittest.TestCase):
    def test_repair_and_demolish_actions_are_accepted_and_normalized(self):
        plan, rejected = build_plan("Fix", 0.8, [
            {"action_type": "repair", "building_type": "Şehir Merkezi", "count": 3, "reason": "fire damage"},
            {"action_type": "DEMOLISH", "building_type": "ev", "target_zone": "North", "reason": "refund"},
            {"action_type": "REPAIR", "building_type": "Med Bay", "reason": "r"},
        ])
        self.assertEqual(rejected, [])
        self.assertEqual(plan["actions"][0], {"action_type": "REPAIR", "building_type": "TownCenter", "reason": "fire damage"})
        self.assertEqual(plan["actions"][1], {"action_type": "DEMOLISH", "building_type": "House", "reason": "refund"})
        self.assertEqual(plan["actions"][2]["building_type"], "HealthCenter")
        self.assertEqual(validate_plan(plan), [])

    def test_town_center_can_never_be_demolished_or_built_and_farms_are_not_buildings(self):
        _, rejected = build_plan("x", 0.5, [
            {"action_type": "DEMOLISH", "building_type": "TownCenter", "reason": "r"},
            {"action_type": "DEMOLISH", "building_type": "Komuta Merkezi", "reason": "r"},
            {"action_type": "BUILD", "building_type": "TownCenter", "reason": "r"},
            {"action_type": "REPAIR", "building_type": "Farm", "reason": "r"},
            {"action_type": "DEMOLISH", "building_type": "Farm", "reason": "r"},
            {"action_type": "REPAIR", "reason": "missing building"},
        ])
        self.assertEqual(len(rejected), 6)
        self.assertTrue(all(r["stage"] == "schema" for r in rejected))

    def test_existing_build_actions_are_unchanged(self):
        self.assertEqual(normalize_action({"action_type": "BUILD", "building_type": "kışla", "count": 4, "reason": "r"}),
                         {"action_type": "BUILD", "building_type": "Barracks", "reason": "r"})
        plan, rejected = build_plan("x", 0.5, [{"action_type": "BUILD", "building_type": "Farm", "reason": "r"}])
        self.assertEqual((len(plan["actions"]), rejected), (1, []))

    def test_answer_schema_and_prompts_offer_repair_and_demolish(self):
        variants = _answer_schema(sorted(ALL_TOOLS))["properties"]["actions"]["items"]["anyOf"]
        by_type = {v["properties"]["action_type"]["const"]: v for v in variants}
        self.assertEqual(by_type["REPAIR"]["properties"]["building_type"]["enum"], list(catalog.REPAIRABLE_TYPES))
        self.assertNotIn("TownCenter", by_type["DEMOLISH"]["properties"]["building_type"]["enum"])
        self.assertNotIn("TownCenter", by_type["BUILD"]["properties"]["building_type"]["enum"])
        self.assertIn("DEMOLISH", ANSWER_SYSTEM)
        self.assertIn("Town Center can NEVER be demolished", ANSWER_SYSTEM)
        self.assertIn("repairing or demolishing buildings need get_army_status", ROUTER_SYSTEM)

    def test_catalog_refund_is_half_of_the_build_cost_rounded_down(self):
        self.assertEqual(catalog.demolish_refund("House"), {"wood": 15, "food": 0, "gold": 0})
        self.assertEqual(catalog.demolish_refund("Stable"), {"wood": 60, "food": 0, "gold": 10})
        self.assertEqual(catalog.demolish_refund("Wall"), {"wood": 5, "food": 0, "gold": 0})
        self.assertEqual(catalog.DEMOLISHABLE_TYPES, tuple(t for t in catalog.REPAIRABLE_TYPES if t != "TownCenter"))


class PrecheckTests(unittest.TestCase):
    def test_repair_charges_the_snapshot_cost_and_needs_a_damaged_building(self):
        warnings = precheck_actions([
            {"action_type": "REPAIR", "building_type": "TownCenter", "reason": "r"},
            {"action_type": "REPAIR", "building_type": "TownCenter", "reason": "second one"},
            {"action_type": "REPAIR", "building_type": "House", "reason": "not damaged"},
            {"action_type": "REPAIR", "building_type": "Barracks", "reason": "already repairing"},
        ], snap())
        self.assertEqual(warnings[0], "")
        self.assertIn("No damaged TownCenter", warnings[1])
        self.assertIn("No damaged House", warnings[2])
        self.assertIn("No damaged Barracks", warnings[3])

    def test_unaffordable_repair_is_flagged(self):
        s = snap()
        poor = s.model_copy(update={"resources": s.resources.model_copy(update={"gold": 5})})
        self.assertIn("gold", precheck_actions([{"action_type": "REPAIR", "building_type": "TownCenter", "reason": "r"}], poor)[0])

    def test_demolish_refund_pays_for_the_next_action(self):
        s = snap()
        poor = s.model_copy(update={"resources": s.resources.model_copy(update={"wood": 10})})
        build = {"action_type": "BUILD", "building_type": "House", "reason": "r"}       # 30 wood
        demolish = {"action_type": "DEMOLISH", "building_type": "Barracks", "reason": "r"}  # +50 wood
        self.assertIn("wood", precheck_actions([build], poor)[0])
        self.assertEqual(precheck_actions([demolish, build], poor), ["", ""])

    def test_demolish_needs_a_free_finished_building_and_workers(self):
        s = snap()
        warnings = precheck_actions([{"action_type": "DEMOLISH", "building_type": "Barracks", "reason": "r"},
                                     {"action_type": "DEMOLISH", "building_type": "Barracks", "reason": "r"},
                                     {"action_type": "DEMOLISH", "building_type": "Stable", "reason": "r"}], s)
        self.assertEqual(warnings[0], "")             # 2 Barracks, 1 already repairing -> one is free
        self.assertIn("No finished Barracks", warnings[1])
        self.assertIn("No finished Stable", warnings[2])
        no_workers = s.model_copy(update={"own_units": [u for u in s.own_units if u.type != "Worker"]})
        self.assertIn("No available Worker",
                      precheck_actions([{"action_type": "DEMOLISH", "building_type": "House", "reason": "r"}], no_workers)[0])


class AgentLoopTests(unittest.TestCase):
    def test_commander_returns_a_repair_plan_from_the_model(self):
        llm = FakeLLM(
            {"category": "strategy", "reasoning": "damaged buildings", "knowledge_query": "repair building",
             "tools": ["get_army_status", "get_player_resources", "search_game_knowledge"]},
            {"on_topic": True, "answer": "Şehir Merkezin %40 canda. Bir işçiyle tamir et.", "confidence": 0.8,
             "actions": [{"action_type": "REPAIR", "building_type": "TownCenter", "reason": "Yangın hasarı."}],
             "need_more_tools": [], "knowledge_query": ""},
        )
        commander = StrategicCommander(llm, INDEX, AgentLogger(enabled=False))
        ctx = context()
        ctx.snapshot = snap()
        r = asyncio.run(commander.run(ctx, "Yangından sonra binalarımı tamir etmeli miyim?"))
        self.assertTrue(r["has_plan"])
        self.assertEqual(r["plan"]["actions"][0]["action_type"], "REPAIR")
        self.assertEqual(r["action_warnings"], [""])
        self.assertIn("rule_repair_demolish_v1", r["sources"])
        self.assertIn('"damaged_buildings":[{"type":"TownCenter"', llm.calls[1][-1]["content"])


class RagTests(unittest.TestCase):
    def test_turkish_and_english_questions_find_the_maintenance_rule(self):
        for q in ("binayı nasıl tamir ederim", "evimi yıkarsam ne kadar kaynak geri alırım", "can I demolish my town center",
                  "how much does a repair cost", "kışlayı yıkmak istiyorum"):
            ids = [h["source_id"] for h in INDEX.search(q, 3)]
            self.assertIn("rule_repair_demolish_v1", ids, (q, ids))

    def test_fire_damage_question_finds_the_disaster_rule(self):
        for q in ("yangın binaya hasar verir mi", "does fire damage my buildings"):
            self.assertEqual(INDEX.search(q, 1)[0]["source_id"], "rule_disasters_v1", q)
        text = INDEX.get("rule_disasters_v1").text
        self.assertIn("25% HP", text)

    def test_old_no_repair_statement_is_gone(self):
        self.assertNotIn("There is no repair action", INDEX.get("rule_disaster_response_v1").text)

    def test_weapon_questions_still_find_weapon_upgrades(self):
        self.assertTrue(INDEX.search("silah yükseltmesi hasarı ne kadar artırır", 1)[0]["source_id"].startswith("tech_weapon"))


class BotMaintenanceTests(unittest.TestCase):
    def test_damaged_building_is_repaired_when_affordable_and_calm(self):
        r = bot_req(damaged_buildings=1, repair_cost={"wood": 25, "food": 0, "gold": 0})
        self.assertEqual(H.candidate_maintenance(H.facts(r)), ["none", "repair"])
        self.assertEqual(H.argmax(H.heuristic(r)["maintenance"]), "repair")

    def test_unaffordable_or_not_allowed_repair_is_never_offered(self):
        poor = bot_req(damaged_buildings=1, repair_cost={"wood": 500, "food": 0, "gold": 0})
        self.assertEqual(H.candidate_maintenance(H.facts(poor)), ["none"])
        self.assertEqual(H.argmax(H.heuristic(poor)["maintenance"]), "none")
        blocked = bot_req(damaged_buildings=1, allowed_maintenance=["none"])
        self.assertEqual(H.candidate_maintenance(H.facts(blocked), blocked.allowed_maintenance), ["none"])

    def test_critical_building_is_demolished_only_under_a_heavy_attack(self):
        siege = bot_req(damaged_buildings=2, critical_buildings=1, repair_cost={"wood": 40, "food": 0, "gold": 0},
                        recent_events=ATTACKS, visible_enemies=[{"type": "Cavalry", "count": 6, "region": "West"}])
        self.assertEqual(H.argmax(H.heuristic(siege)["maintenance"]), "demolish")
        calm = bot_req(damaged_buildings=2, critical_buildings=1, repair_cost={"wood": 40, "food": 0, "gold": 0})
        self.assertEqual(H.argmax(H.heuristic(calm)["maintenance"]), "repair")

    def test_no_damage_means_no_maintenance_question(self):
        r = bot_req()
        self.assertEqual(H.argmax(H.heuristic(r)["maintenance"]), "none")
        self.assertNotIn("maintenance", bot_decider.build_questions(r))

    def test_laya_question_state_and_blend_include_maintenance(self):
        r = bot_req(damaged_buildings=1, critical_buildings=1, repair_cost={"wood": 25, "food": 0, "gold": 0})
        q = bot_decider.build_questions(r)
        self.assertEqual(list(q["maintenance"]["criteria"]), ["none", "repair", "demolish"])
        self.assertIn("50%", q["maintenance"]["criteria"]["demolish"])
        self.assertIn("Damaged buildings 1 critical 1", bot_decider.build_state(r))
        # heuristic: none 0.6, repair 2.0, demolish 0 (calm) -> 0.23 / 0.77 / 0
        laya = [{"id": "maintenance", "type": "choice", "choice": "none", "p": 0.7,
                 "options": [{"label": "none", "p": 0.7}, {"label": "repair", "p": 0.25}, {"label": "demolish", "p": 0.05}]}]
        blended = {d["id"]: d for d in bot_decider.blended_decisions(r, laya, BotConfig(), 0.4)}
        self.assertEqual(blended["maintenance"]["laya"], "none")
        self.assertEqual(blended["maintenance"]["heuristic"], "repair")
        # 0.4 * Laya + 0.6 * heuristic: none 0.28 + 0.14 = 0.42 < repair 0.10 + 0.46 = 0.56
        self.assertEqual(blended["maintenance"]["choice"], "repair")
        strong_laya = [dict(laya[0], options=[{"label": "none", "p": 0.95}, {"label": "repair", "p": 0.05}])]
        self.assertEqual({d["id"]: d for d in bot_decider.blended_decisions(r, strong_laya, BotConfig(), 0.4)}
                         ["maintenance"]["choice"], "none")   # a confident Laya can still override the heuristic

    def test_old_unity_bot_request_without_maintenance_fields_still_validates(self):
        r = bot_req()
        self.assertEqual((r.damaged_buildings, r.critical_buildings, r.repair_cost.wood, r.allowed_maintenance), (0, 0, 0, None))

    def test_bot_rag_adds_the_maintenance_rule_when_repair_is_likely(self):
        r = bot_req(damaged_buildings=1, repair_cost={"wood": 25, "food": 0, "gold": 0})
        res = asyncio.run(bot_rag.enrich(r, INDEX, None, BotConfig(), "unit-test-session-00"))
        self.assertIn("rule_repair_demolish_v1", res.source_ids)
        calm = asyncio.run(bot_rag.enrich(bot_req(), INDEX, None, BotConfig(), "unit-test-session-00"))
        self.assertNotIn("rule_repair_demolish_v1", calm.source_ids)


if __name__ == "__main__":
    unittest.main()
