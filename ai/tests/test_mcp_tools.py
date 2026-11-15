"""Calls every MCP tool through a real MCP client session with valid and invalid inputs (Tutorial 1 acceptance)."""

import asyncio
import unittest

from mcp import Client

from mcp_server.server import ALL_TOOLS, build_server
from rag.retriever import KnowledgeIndex
from tests.helpers import context

INDEX = KnowledgeIndex.load()


def call(tool, args, **snapshot_overrides):
    async def go():
        async with Client(build_server(context(**snapshot_overrides), INDEX)) as c:
            r = await c.call_tool(tool, args)
            return r.is_error, r.structured_content
    return asyncio.run(go())


class McpToolTests(unittest.TestCase):
    def test_lists_all_tools_with_three_or_more_live_state_tools(self):
        async def go():
            async with Client(build_server(context(), INDEX)) as c:
                return sorted(t.name for t in (await c.list_tools()).tools)
        names = asyncio.run(go())
        self.assertEqual(names, sorted(ALL_TOOLS))
        self.assertGreaterEqual(len(names), 5)

    def test_resources_and_affordability(self):
        err, data = call("get_player_resources", {})
        self.assertFalse(err)
        self.assertEqual(data["resources"], {"wood": 420, "food": 180, "gold": 250})
        self.assertEqual(data["population"]["free"], 16)
        self.assertEqual(data["max_affordable_units_now"]["Spearman"], 3)  # 180 food / 60

    def test_army_status_and_matchups(self):
        err, data = call("get_army_status", {"include_workers": False})
        self.assertFalse(err)
        self.assertNotIn("Worker", [u["type"] for u in data["units"]])
        self.assertEqual(data["matchups_vs_visible_enemies"]["Spearman"]["strong_against_visible"], ["Cavalry"])

    def test_visible_enemies_only_returns_snapshot_data(self):
        err, data = call("get_visible_enemies", {})
        self.assertFalse(err)
        self.assertEqual(data["visible_unit_total"], 4)
        self.assertEqual(data["visible_units"][0]["countered_by"], "Spearman")
        self.assertNotIn("resources", data)

    def test_identity_argument_cannot_switch_player(self):
        err, data = call("get_visible_enemies", {"player_id": "opponent"})
        self.assertEqual(data["visible_unit_total"], 4)  # still the session's own fog-filtered view

    def test_technology_status_next_tiers(self):
        err, data = call("get_technology_status", {})
        self.assertFalse(err)
        self.assertEqual(data["next_tiers"]["weapon"]["cost"], {"wood": 0, "food": 60, "gold": 80})
        self.assertEqual(data["next_tiers"]["armor"]["tier"], 2)
        self.assertFalse(data["research_building_ready"])

    def test_recent_events_valid_and_out_of_range(self):
        err, data = call("get_recent_events", {"last_seconds": 9})
        self.assertFalse(err)
        self.assertEqual(data["count"], 1)
        err, _ = call("get_recent_events", {"last_seconds": 100000})
        self.assertTrue(err)

    def test_estimate_plan_cost(self):
        err, data = call("estimate_plan_cost", {"items": [{"kind": "unit", "id": "Spearman", "count": 5}]})
        self.assertFalse(err)
        self.assertEqual(data["total"], {"wood": 0, "food": 300, "gold": 100})
        self.assertFalse(data["affordable"])
        self.assertEqual(data["shortage"], {"food": 120})

    def test_estimate_plan_cost_accepts_scifi_names_and_tech_lines(self):
        err, data = call("estimate_plan_cost", {"items": [{"kind": "unit", "id": "Marine", "count": 1},
                                                           {"kind": "tech", "id": "weapon"}]})
        self.assertFalse(err)
        self.assertEqual(data["total"], {"wood": 0, "food": 120, "gold": 100})

    def test_estimate_plan_cost_rejects_invalid_inputs(self):
        self.assertTrue(call("estimate_plan_cost", {"items": [{"kind": "unit", "id": "Dragon", "count": 1}]})[0])
        self.assertTrue(call("estimate_plan_cost", {"items": [{"kind": "unit", "id": "Spearman", "count": -3}]})[0])
        self.assertTrue(call("estimate_plan_cost", {"items": []})[0])

    def test_search_game_knowledge_valid_and_invalid(self):
        err, data = call("search_game_knowledge", {"query": "counter cavalry", "top_k": 2})
        self.assertFalse(err)
        self.assertEqual(len(data["results"]), 2)
        self.assertTrue(all("source_id" in r for r in data["results"]))
        self.assertTrue(call("search_game_knowledge", {"query": "counter cavalry", "top_k": 99})[0])
        self.assertTrue(call("search_game_knowledge", {"query": "x"})[0])


if __name__ == "__main__":
    unittest.main()
