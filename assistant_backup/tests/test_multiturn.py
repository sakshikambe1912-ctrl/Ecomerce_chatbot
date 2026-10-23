"""Multi-turn conversations end to end with a mocked LLM (Phase 6.3)."""
from conversations.models import Conversation
from assistant.tests.fakes import extraction, route
from assistant.tests.test_chat_api import ChatAPITestBase

START = extraction(category="headphones", keywords=["headphones"], max_price=350, currency="USD")


class MultiTurnTests(ChatAPITestBase):
    def turn(self, message, conversation_id=None, **extracted):
        llm = route(extraction(**extracted)) if extracted else route(START)
        response = self.chat(message, conversation_id=conversation_id, llm=llm)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def start(self):
        first = self.turn("Suggest headphones under $350")
        self.assertTrue(first["products"])
        return first

    def titles(self, data):
        return [p["title"] for p in data["products"]]

    def test_budget_change_keeps_category(self):
        first = self.start()
        self.assertNotIn("Sennheiser Momentum 4 Wireless Headphones", self.titles(first))
        second = self.turn("increase my budget to 400", first["conversation_id"], max_price=400)
        self.assertEqual(second["requirements"]["category"], "headphones")
        self.assertEqual(second["requirements"]["max_price"], 400.0)
        self.assertIn("Sennheiser Momentum 4 Wireless Headphones", self.titles(second))
        self.assertNotIn("Apple MacBook Air 13-inch Laptop with M3 chip", self.titles(second))

    def test_brand_change_then_brand_removal(self):
        first = self.start()
        sony = self.turn("only Sony", first["conversation_id"], brand="Sony", keywords=["sony"])
        self.assertEqual(set(self.titles(sony)), {"Sony WH-1000XM5 Wireless Noise Canceling Headphones",
                                                 "Sony WH-CH520 Wireless Headphones"})
        bose = self.turn("actually show Bose", first["conversation_id"], brand="Bose")
        self.assertEqual(self.titles(bose), ["Bose QuietComfort Headphones"])
        everything = self.turn("show all brands", first["conversation_id"])
        self.assertIsNone(everything["requirements"]["brand"])
        self.assertEqual(everything["requirements"]["max_price"], 350.0)
        self.assertGreaterEqual(len(everything["products"]), 4)

    def test_rating_question_sorts_by_rating(self):
        first = self.start()
        rated = self.turn("which has the best rating?", first["conversation_id"], sort_by="rating")
        ratings = [p["rating"] for p in rated["products"]]
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        best = [f for f in rated["comparison"]["facts"] if f["kind"] == "best_rated"][0]
        self.assertEqual(best["titles"], ["Sony WH-1000XM5 Wireless Noise Canceling Headphones"])

    def test_comparison_of_previous_results(self):
        first = self.start()
        compared = self.turn("compare these", first["conversation_id"], intent="product_comparison")
        compared_ids = [row["id"] for row in compared["comparison"]["products"]]
        self.assertEqual(set(compared_ids), {p["id"] for p in first["products"][:5]})

    def test_constraint_removal(self):
        first = self.start()
        removed = self.turn("remove the budget limit", first["conversation_id"], max_price=350)
        self.assertIsNone(removed["requirements"]["max_price"])
        self.assertIn("Sennheiser Momentum 4 Wireless Headphones", self.titles(removed))

    def test_unrelated_question_mid_conversation_keeps_memory(self):
        first = self.start()
        detour = self.turn("write a python script to sort a list", first["conversation_id"])
        self.assertEqual(detour["intent"], "out_of_scope")
        self.assertEqual(detour["products"], [])
        memory = Conversation.objects.get(id=first["conversation_id"]).current_requirements
        self.assertEqual(memory["max_price"], 350.0)
        back = self.turn("only Sony", first["conversation_id"], brand="Sony")
        self.assertEqual(back["requirements"]["max_price"], 350.0)
        self.assertEqual(back["requirements"]["category"], "headphones")

    def test_new_conversation_starts_clean(self):
        first = self.start()
        self.turn("only Sony", first["conversation_id"], brand="Sony")
        fresh = self.turn("show me laptops", category="laptop", keywords=["laptop"])
        self.assertNotEqual(fresh["conversation_id"], first["conversation_id"])
        self.assertIsNone(fresh["requirements"]["brand"])
        self.assertIsNone(fresh["requirements"]["max_price"])
        self.assertEqual(self.titles(fresh), ["Apple MacBook Air 13-inch Laptop with M3 chip"])
