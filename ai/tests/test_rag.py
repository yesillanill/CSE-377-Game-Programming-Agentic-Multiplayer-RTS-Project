import unittest

from rag.retriever import KnowledgeIndex, load_chunks, tokenize


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = KnowledgeIndex(load_chunks())

    def top(self, query, k=3):
        return [h["source_id"] for h in self.index.search(query, k)]

    def test_knowledge_base_meets_minimum_content(self):
        kinds = {}
        for c in self.index.chunks:
            kinds[c.kind] = kinds.get(c.kind, 0) + 1
        self.assertGreaterEqual(kinds["unit"], 4)
        self.assertGreaterEqual(kinds["technology"], 4)
        self.assertGreaterEqual(kinds["rule"] + kinds["strategy"], 5)

    def test_english_counter_query(self):
        self.assertIn("rule_counter_triangle_v1", self.top("counter cavalry"))

    def test_turkish_query_is_mapped_to_english_vocabulary(self):
        self.assertIn("cavalry", tokenize("Süvarilere karşı ne kullanmalıyım?"))
        self.assertEqual(self.top("Demir silahlar ne işe yarar?")[0], "tech_weapon_2_v1")
        self.assertEqual(self.top("nüfus sınırı nasıl artar")[0], "building_house_v1")
        self.assertEqual(self.top("maden ne kadar altın üretir")[0], "building_mine_v1")

    def test_results_have_source_ids_scores_and_text(self):
        hit = self.index.search("What does Iron Weapons do?", 1)[0]
        self.assertEqual(hit["source_id"], "tech_weapon_2_v1")
        self.assertGreater(hit["score"], 0)
        self.assertIn("30%", hit["text"])

    def test_unrelated_query_returns_nothing(self):
        self.assertEqual(self.index.search("zzzz qqqq", 3), [])

    def test_index_round_trip(self):
        again = KnowledgeIndex.from_json(self.index.to_json())
        self.assertEqual(self.top("win condition"), [h["source_id"] for h in again.search("win condition", 3)])


if __name__ == "__main__":
    unittest.main()
