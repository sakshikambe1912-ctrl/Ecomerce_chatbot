"""RequirementsService: extraction (mocked LLM) and deterministic memory merge."""
from django.test import SimpleTestCase

from assistant.services.requirements_service import RequirementsService, ShoppingRequirements
from assistant.tests.fakes import extraction, patch_llm

PREVIOUS = {
    "intent": "product_search",
    "keywords": ["headphones"],
    "category": "headphones",
    "brand": None,
    "min_price": None,
    "max_price": 350.0,
    "currency": "USD",
    "min_rating": None,
    "only_available": True,
    "must_have_features": [],
    "sort_by": "relevance",
}


class MergeRequirementsTests(SimpleTestCase):
    def merge(self, message, previous=None, **new_fields):
        with patch_llm():
            service = RequirementsService()
        new = ShoppingRequirements(**new_fields)
        return service.merge_requirements(previous or dict(PREVIOUS), new, user_message=message)

    def test_only_sony_keeps_budget_and_category(self):
        merged = self.merge("only Sony", brand="Sony", keywords=["sony"])
        self.assertEqual(merged.brand, "Sony")
        self.assertEqual(merged.max_price, 350.0)
        self.assertEqual(merged.category, "headphones")

    def test_highest_rated_keeps_constraints_and_sorts_by_rating(self):
        merged = self.merge("show highest rated", sort_by="rating", min_rating=4.0)
        self.assertEqual(merged.sort_by, "rating")
        self.assertEqual(merged.max_price, 350.0)
        self.assertEqual(merged.category, "headphones")

    def test_increase_budget(self):
        merged = self.merge("increase my budget to 400", max_price=400)
        self.assertEqual(merged.max_price, 400.0)
        self.assertEqual(merged.category, "headphones")

    def test_remove_budget_even_if_model_kept_it(self):
        merged = self.merge("remove the budget limit", max_price=350)
        self.assertIsNone(merged.max_price)
        self.assertIsNone(merged.min_price)
        self.assertEqual(merged.category, "headphones")

    def test_brand_replace(self):
        previous = dict(PREVIOUS, brand="Sony")
        merged = self.merge("actually show Bose", previous=previous, brand="Bose")
        self.assertEqual(merged.brand, "Bose")

    def test_brand_removal(self):
        previous = dict(PREVIOUS, brand="Sony")
        merged = self.merge("show all brands", previous=previous)
        self.assertIsNone(merged.brand)
        self.assertEqual(merged.max_price, 350.0)

    def test_feature_removal(self):
        previous = dict(PREVIOUS, must_have_features=["noise cancellation"])
        merged = self.merge("remove that feature", previous=previous)
        self.assertEqual(merged.must_have_features, [])

    def test_feature_is_kept_when_not_mentioned(self):
        previous = dict(PREVIOUS, must_have_features=["noise cancellation"])
        merged = self.merge("which is cheapest?", previous=previous, sort_by="price_ascending")
        self.assertEqual(merged.must_have_features, ["noise cancellation"])
        self.assertEqual(merged.sort_by, "price_ascending")

    def test_category_change(self):
        merged = self.merge("show me laptops instead", category="laptop", keywords=["laptop"])
        self.assertEqual(merged.category, "laptop")

    def test_general_question_does_not_change_memory(self):
        previous = dict(PREVIOUS)
        merged = self.merge("hello", previous=previous, intent="general_question")
        self.assertEqual(merged.intent, "general_question")
        self.assertEqual(previous, PREVIOUS)


class ExtractTests(SimpleTestCase):
    def test_extract_applies_deterministic_rules(self):
        with patch_llm([extraction(keywords=["headphones"])]):
            result = RequirementsService().extract("Suggest headphones under $350")
        self.assertEqual(result.category, "headphones")
        self.assertEqual(result.max_price, 350.0)
        self.assertEqual(result.currency, "USD")

    def test_history_is_included_in_prompt(self):
        history = [
            {"role": "user", "content": "Suggest headphones under $350"},
            {"role": "assistant", "content": "Here are three options."},
        ]
        with patch_llm([extraction()]) as fake:
            RequirementsService().extract("Which has the best rating?", conversation_history=history)
        prompt = fake.prompt_text(0)
        self.assertIn("User: Suggest headphones under $350", prompt)
        self.assertIn("Assistant: Here are three options.", prompt)

    def test_empty_message_rejected(self):
        with patch_llm():
            with self.assertRaises(ValueError):
                RequirementsService().extract("   ")

    def test_invalid_json_recovers(self):
        with patch_llm(["not json", "still not json"]):
            result = RequirementsService().extract("headphones under $100")
        self.assertEqual(result.category, "headphones")
        self.assertEqual(result.max_price, 100.0)

    def test_retry_uses_strict_instruction_and_second_answer(self):
        with patch_llm(["not json", extraction(category="laptop", keywords=["laptop"])]) as fake:
            result = RequirementsService().extract("show me laptops")
        self.assertEqual(result.category, "laptop")
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("Return ONLY one JSON object", fake.prompt_text(1))

    def test_schema_violation_is_treated_like_invalid_json(self):
        bad = extraction(min_price=500, max_price=100)
        with patch_llm([bad, bad]):
            result = RequirementsService().extract("cheapest headphones")
        self.assertEqual(result.category, "headphones")
        self.assertEqual(result.sort_by, "price_ascending")

    def test_heuristic_understands_budget_change(self):
        with patch_llm(["?", "?"]):
            result = RequirementsService().extract("increase my budget to 400")
        self.assertEqual(result.max_price, 400.0)

    def test_nothing_understood_asks_for_clarification(self):
        with patch_llm(["?", "?"]):
            result = RequirementsService().extract("hmm maybe something nice")
        self.assertEqual(result.intent, "clarification_needed")

    def test_provider_error_becomes_model_unavailable(self):
        import httpx
        import openai

        from assistant.services.errors import ModelUnavailableError

        error = openai.APITimeoutError(request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"))
        with patch_llm([error]):
            with self.assertRaises(ModelUnavailableError):
                RequirementsService().extract("headphones")
