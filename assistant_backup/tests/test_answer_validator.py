"""Answer validation: only verified prices, ratings and links survive."""
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from assistant.services.answer_validator import find_violations, render_template_answer, validate_answer
from assistant.services.requirements_service import ShoppingRequirements
from assistant.tests.factories import build_catalog
from assistant.tests.fakes import embed_products, extraction, patch_embeddings, patch_llm, route
from products.models import Product

SONY = {"id": 1, "title": "Sony WH-1000XM5", "brand": "Sony", "price": "1099.00", "original_price": "1199.00",
        "currency": "USD", "rating": 4.7, "is_available": True, "website_name": "Alpha Store",
        "product_url": "https://alpha.example.com/p/1", "image_url": ""}


class ValidatorUnitTests(SimpleTestCase):
    def test_supported_values_pass(self):
        answer = ("**Sony WH-1000XM5** - Price: 1,099.00 USD (was $1199) - Rating: 4.7/5 - "
                  "30-hour battery, M3 chip, 2 USB ports - Link: https://alpha.example.com/p/1.")
        self.assertEqual(find_violations(answer, [SONY]), [])

    def test_invented_price(self):
        self.assertTrue(find_violations("Now only $999!", [SONY]))
        self.assertTrue(find_violations("Price: 899.00 USD", [SONY]))

    def test_invented_rating(self):
        self.assertTrue(find_violations("Rating: 4.9", [SONY]))
        self.assertTrue(find_violations("rated 5 stars by everyone", [SONY]))

    def test_invented_url(self):
        self.assertTrue(find_violations("Buy at https://evil.example.com/deal", [SONY]))

    def test_user_budget_may_be_repeated(self):
        requirements = ShoppingRequirements(max_price=1200, currency="USD", min_rating=4.5)
        answer, valid = validate_answer("Here is an option under $1200 rated 4.5 stars or more.", [SONY], requirements)
        self.assertTrue(valid)

    def test_template_uses_only_record_values(self):
        text = render_template_answer([SONY, dict(SONY, product_url="", title="No Link")])
        self.assertIn("1099.00 USD", text)
        self.assertIn("https://alpha.example.com/p/1", text)
        self.assertEqual(text.count("Link:"), 1)


class ValidatorChatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = build_catalog()
        embed_products(Product.objects.all())

    def setUp(self):
        cache.clear()

    def test_invented_price_and_url_are_replaced_by_template(self):
        invented = "Best pick: **Sony WH-1000XM5** for just $199 at https://cheap.example.com/sony"
        llm = route(extraction(category="headphones", keywords=["headphones"]), answer=invented)
        with patch_llm(default=llm), patch_embeddings():
            body = APIClient().post("/api/chat/", {"message": "Suggest headphones under $350",
                                                   "website_ids": [self.c["usd_site"].id]}, format="json").json()
        self.assertNotIn("$199", body["answer"])
        self.assertNotIn("cheap.example.com", body["answer"])
        self.assertIn("328.00 USD", body["answer"])
