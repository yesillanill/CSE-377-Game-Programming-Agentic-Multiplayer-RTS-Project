"""Contract test: JSON exactly as Unity's JsonUtility writes AiSafeSnapshot (every field present, empty strings,
floats) must validate on the gateway; hidden-information fields must be rejected."""

import copy
import json
import unittest

from pydantic import ValidationError

from mcp_server.session import SafeSnapshot, SessionStore

UNITY_JSON = """{"match_id":"Room_1","game_mode":"SciFi","ui_language":"tr","game_time_seconds":12.0,
"map_size":{"x":64,"y":48},"base_region":"Unknown","resources":{"wood":200,"food":200,"gold":100},
"population":{"current":5,"max":25,"queued":0},
"own_units":[{"type":"Worker","display_name":"Engineer","count":5,"region":"SouthWest","idle":5}],
"own_buildings":[{"type":"TownCenter","display_name":"Command Center","count":1,"under_construction":0,"queued_units":0,"region":"SouthWest"},
                 {"type":"Wall","display_name":"","count":12,"under_construction":2,"queued_units":0,"region":"West"}],
"visible_enemies":[],"visible_enemy_buildings":[],
"tech":{"weapon_level":0,"armor_level":0,"wall_level":0,"researching":"","research_progress":0.0,"researched":[]},
"recent_events":[{"type":"UNIT_TRAINED","detail":"Worker","region":"SouthWest","seconds_ago":3.0}]}"""


class UnityContractTests(unittest.TestCase):
    def test_unity_style_json_validates(self):
        snap = SafeSnapshot.model_validate(json.loads(UNITY_JSON))
        self.assertEqual(snap.map_size.y, 48)
        self.assertEqual(snap.own_buildings[1].type, "Wall")

    def test_hidden_information_fields_are_rejected(self):
        for field, value in [("enemy_resources", {"gold": 999}), ("hidden_enemies", []), ("opponent_tech", {})]:
            data = json.loads(UNITY_JSON)
            data[field] = value
            with self.assertRaises(ValidationError):
                SafeSnapshot.model_validate(data)

    def test_unknown_unit_types_and_bad_ranges_are_rejected(self):
        data = json.loads(UNITY_JSON)
        bad = copy.deepcopy(data)
        bad["visible_enemies"] = [{"type": "Dragon", "display_name": "", "count": 1, "region": "North"}]
        with self.assertRaises(ValidationError):
            SafeSnapshot.model_validate(bad)
        bad = copy.deepcopy(data)
        bad["tech"]["weapon_level"] = 9
        with self.assertRaises(ValidationError):
            SafeSnapshot.model_validate(bad)

    def test_session_token_is_bound_to_one_match(self):
        store = SessionStore()
        snap = SafeSnapshot.model_validate(json.loads(UNITY_JSON))
        store.bind("token-abcdefghijklmnop", snap)
        other = snap.model_copy(update={"match_id": "another"})
        with self.assertRaises(PermissionError):
            store.bind("token-abcdefghijklmnop", other)


if __name__ == "__main__":
    unittest.main()
