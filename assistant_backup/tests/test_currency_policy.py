"""Currency policy: never mix or convert currencies."""
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from assistant.services.currency_policy import currency_from_reply, decide_currency
from assistant.services.requirements_service import ShoppingRequirements
from assistant.tests.factories import build_catalog
from assistant.tests.fakes import embed_products, extraction, patch_embeddings, patch_llm, route
from products.models import Product


def req(**fields):
    fields.setdefault("keywords", [fields["category"]] if fields.get("category") else [])
    return ShoppingRequirements(**fields)


class DecideCurrencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = build_catalog()
        cls.usd, cls.inr = cls.c["usd_site"].id, cls.c["inr_site"].id

    def test_stated_currency_wins(self):
        self.assertEqual(decide_currency(req(category="headphones", currency="inr"), [self.usd, self.inr]).currency, "INR")

    def test_single_currency_in_scope_is_used(self):
        decision = decide_currency(req(category="headphones"), [self.usd])
        self.assertEqual(decision.currency, "USD")
        self.assertIsNone(decision.clarification)

    def test_only_matching_products_count(self):
        # Laptops exist only on the USD site, so no question is needed.
        decision = decide_currency(req(category="laptop"), [self.usd, self.inr])
        self.assertEqual(decision.currency, "USD")

    def test_several_currencies_ask_and_list_codes(self):
        decision = decide_currency(req(category="headphones"), [self.usd, self.inr])
        self.assertIsNone(decision.currency)
        self.assertIn("INR", decision.clarification)
        self.assertIn("USD", decision.clarification)
        self.assertEqual(decision.options, ["INR", "USD"])

    def test_reply_parsing(self):
        self.assertEqual(currency_from_reply("USD please", ["INR", "USD"]), "USD")
        self.assertEqual(currency_from_reply("in rupees", ["INR", "USD"]), "INR")
        self.assertEqual(currency_from_reply("$", ["INR", "USD"]), "USD")
        self.assertIsNone(currency_from_reply("show laptops", ["INR", "USD"]))


class CurrencyChatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = build_catalog()
        cls.usd, cls.inr = cls.c["usd_site"].id, cls.c["inr_site"].id
        embed_products(Product.objects.all())

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def chat(self, message, conversation_id=None):
        body = {"message": message, "website_ids": [self.usd, self.inr]}
        if conversation_id:
            body["conversation_id"] = conversation_id
        llm = route(extraction(category="headphones", keywords=["headphones"]))
        with patch_llm(default=llm), patch_embeddings():
            return self.client.post("/api/chat/", body, format="json").json()

    def test_mixed_currencies_ask_then_resume(self):
        first = self.chat("Show me headphones")
        self.assertEqual(first["intent"], "clarification_needed")
        self.assertEqual(first["products"], [])
        self.assertIn("USD", first["answer"])

        second = self.chat("USD", conversation_id=first["conversation_id"])
        self.assertEqual(second["intent"], "product_search")
        self.assertTrue(second["products"])
        self.assertTrue(all(p["currency"] == "USD" for p in second["products"]))
        self.assertEqual(second["requirements"]["category"], "headphones")
