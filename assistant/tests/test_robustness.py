"""
The chatbot must give correct answers even when the user never starts a new
conversation and the (small) language model extracts wrong or invented fields.

The catalog is the real ShopZone data (products-export.json). The extraction
results used here are the ones the small model actually produced in manual testing:
invented categories ("home_appliances", "Footwear"), underscore features
("noise_cancellation"), and product questions filed as general advice.
"""
import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from assistant.services.conversation_context import is_follow_up, might_follow_up
from assistant.services.product_lookup import facts_answer, find_named_products
from assistant.services.product_search_service import ProductSearchService
from assistant.services.requirements_service import ShoppingRequirements
from assistant.tests.factories import create_product, create_website
from assistant.tests.fakes import embed_products, extraction, patch_embeddings, patch_llm, route
from products.models import Product

URL = "/api/chat/"
BRANDS = ["Apple", "Sony", "Nike", "Logitech", "Dyson", "Razer", "Ray-Ban", "Nespresso", "Instant Pot", "Anker"]


def load_shopzone():
    site = create_website("ShopZone", currency="USD")
    data = json.loads((Path(settings.BASE_DIR) / "products-export.json").read_text(encoding="utf-8"))
    for item in data:
        brand = next((b for b in BRANDS if item["title"].lower().startswith(b.lower())), "")
        create_product(
            site,
            external_product_id=str(item["id"]),
            title=item["title"],
            brand=brand,
            category=item["category"],
            description=item["description"],
            price=Decimal(str(item["price"])),
            original_price=Decimal(str(item["originalPrice"])),
            rating=Decimal(str(item["rating"])),
            review_count=item["reviewsCount"],
            features=item["features"],
            is_available=item["inStock"],
        )
    return site


class ShopZoneBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.site = load_shopzone()
        embed_products(Product.objects.all())

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def ask(self, message, conversation_id=None, answer="Here are the matching products.", **extracted):
        cache.clear()
        body = {"message": message, "website_ids": [self.site.id]}
        if conversation_id:
            body["conversation_id"] = conversation_id
        with patch_llm(default=route(extraction(**extracted), answer=answer)) as fake, patch_embeddings():
            response = self.client.post(URL, body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        data["_fake"] = fake
        return data

    @staticmethod
    def titles(data):
        return [p["title"] for p in data["products"]]


class SearchRegressionTests(ShopZoneBase):
    def search(self, **fields):
        return [p["title"] for p in ProductSearchService().search(ShoppingRequirements(**fields), [self.site.id])]

    def test_keyword_only_search_returns_only_matching_products(self):
        # Used to return all 16 products: the rating bonus made every score positive.
        self.assertEqual(self.search(keywords=["shoes"]), ["Nike Air Max 270 Men's Running Shoes - Triple Black"])

    def test_filler_words_do_not_match_everything(self):
        self.assertEqual(self.search(keywords=["show me shoes"]), ["Nike Air Max 270 Men's Running Shoes - Triple Black"])

    def test_underscore_feature_matches_title_wording(self):
        found = self.search(category="headphones", must_have_features=["noise_cancellation"])
        self.assertEqual(found, ["Sony WH-1000XM5 Wireless Noise Canceling Headphones"])

    def test_plural_category_matches_singular_text(self):
        self.assertEqual(len(self.search(category="Watches")), 2)


class FollowUpRuleTests(SimpleTestCase):
    PREVIOUS = {"category": "headphones", "keywords": ["headphones"], "brand": "Sony", "max_price": 350}

    def req(self, **fields):
        return ShoppingRequirements(**fields)

    def test_new_topic_is_not_a_follow_up(self):
        self.assertFalse(is_follow_up("Gaming keyboard", self.req(keywords=["gaming keyboard"]), self.PREVIOUS))
        self.assertFalse(is_follow_up("I want to make coffee at home", self.req(keywords=["coffee"]), self.PREVIOUS))
        self.assertFalse(is_follow_up("Something to wear on my wrist", self.req(), self.PREVIOUS))

    def test_whole_catalog_requests_are_new(self):
        self.assertFalse(is_follow_up("Products under $50", self.req(max_price=50), self.PREVIOUS))
        self.assertFalse(is_follow_up("Apple products", self.req(brand="Apple"), self.PREVIOUS))
        self.assertFalse(is_follow_up("Which is the cheapest product?", self.req(sort_by="price_ascending"), self.PREVIOUS))

    def test_real_follow_ups(self):
        self.assertTrue(is_follow_up("Increase my budget to 400", self.req(max_price=400), self.PREVIOUS))
        self.assertTrue(is_follow_up("only Sony", self.req(brand="Sony"), self.PREVIOUS))
        self.assertTrue(is_follow_up("Which has the best rating?", self.req(sort_by="rating"), self.PREVIOUS))
        self.assertTrue(is_follow_up("compare these", self.req(), self.PREVIOUS))
        self.assertTrue(is_follow_up("remove the budget limit", self.req(), self.PREVIOUS))

    def test_same_topic_is_a_refinement(self):
        self.assertTrue(is_follow_up("Sony headphones under $300", self.req(keywords=["headphones"], max_price=300), self.PREVIOUS))

    def test_nothing_to_follow(self):
        self.assertFalse(is_follow_up("Increase my budget", self.req(max_price=400), {}))

    def test_history_shown_to_model_only_when_it_could_matter(self):
        self.assertFalse(might_follow_up("Something to read books on the beach"))
        self.assertTrue(might_follow_up("cheaper ones please"))


class OneConversationTests(ShopZoneBase):
    """Every question is asked in the SAME conversation, as a user who never clicks 'New conversation'."""

    def setUp(self):
        super().setUp()
        first = self.ask(
            "Wireless noise cancelling headphones",
            category="headphones", keywords=["headphones"], brand="Sony",
            must_have_features=["wireless", "noise_cancellation"], min_rating=4.5,
        )
        self.assertEqual(self.titles(first), ["Sony WH-1000XM5 Wireless Noise Canceling Headphones"])
        self.cid = first["conversation_id"]

    def check(self, message, expected_titles, **extracted):
        data = self.ask(message, self.cid, **extracted)
        self.assertEqual(sorted(self.titles(data)), sorted(expected_titles), msg=f"{message!r}: {data['answer']}")
        # Nothing from the headphone question may leak into this one.
        req = data["requirements"]
        self.assertEqual(req.get("must_have_features"), [], msg=message)
        return data

    def test_unrelated_questions_do_not_inherit_earlier_filters(self):
        razer = "Razer BlackWidow V4 Mechanical RGB Gaming Keyboard"
        self.check("Gaming keyboard", [razer], keywords=["gaming keyboard"])
        self.check("Products under $50", ["Ceramic Minimalist Indoor Plant Pot Set with Drainage (3 Pack)"], max_price=50)
        self.check("Electronics under $150", [
            "Kindle Paperwhite (16 GB) – Now with 6.8\" display and warm light",
            "Anker 737 Power Bank (PowerCore 24K), 140W 3-Port Portable Charger",
        ], category="Electronics", max_price=150)
        self.check("Apple products", [
            "Apple iPhone 15 Pro (128 GB) - Natural Titanium",
            "Apple 2024 MacBook Air 13-inch Laptop with M3 chip",
            "Apple Watch Ultra 2 [GPS + Cellular 49mm] Smartwatch",
        ], brand="Apple")

    def test_invented_categories_are_not_enforced(self):
        dyson = "Dyson V15 Detect Cordless Vacuum Cleaner"
        self.check("I need a vacuum cleaner", [dyson], category="home_appliances", keywords=["vacuum cleaner"])
        self.check("How long does the Dyson run on one charge?", [dyson], category="electronic_devices", keywords=["dyson"])
        self.check("Does the Nike shoe come in size 12?", ["Nike Air Max 270 Men's Running Shoes - Triple Black"],
                   category="Footwear", keywords=["nike shoe"])

    def test_plural_category_and_cheapest(self):
        data = self.check("Cheapest watch?", [
            "Classic Minimalist Chronograph Leather Watch for Men",
            "Apple Watch Ultra 2 [GPS + Cellular 49mm] Smartwatch",
        ], category="Watches", sort_by="price_ascending")
        self.assertEqual(data["products"][0]["price"], "68.00")

    def test_near_misses_are_explained_not_listed_as_matches(self):
        laptops = self.ask("Laptops under $1000", self.cid, category="laptop", keywords=["laptop"], max_price=1000)
        self.assertEqual(laptops["products"], [])
        self.assertEqual([a["title"] for a in laptops["alternatives"]], ["Apple 2024 MacBook Air 13-inch Laptop with M3 chip"])
        sony = self.ask("Sony headphones under $300", self.cid, category="headphones", brand="Sony", max_price=300)
        self.assertEqual(sony["products"], [])
        self.assertEqual(len(sony["alternatives"]), 1)

    def test_product_questions_are_answered_from_the_catalog(self):
        price = self.ask("What is the price of the PlayStation 5?", self.cid, intent="general_question")
        self.assertIn("449.99 USD", price["answer"])
        self.assertNotIn("General advice", price["answer"])
        self.assertEqual(self.titles(price), ["PlayStation 5 Digital Edition Console (Slim)"])

        stock = self.ask("Is the iPhone 15 Pro in stock?", self.cid, intent="general_question")
        self.assertIn("in stock", stock["answer"])

        kindle = self.ask("Is the Kindle waterproof?", self.cid, intent="general_question", answer="Yes, the Kindle is waterproof (IPX8).")
        self.assertIn("IPX8", kindle["_fake"].prompt_text())
        self.assertEqual(len(kindle["products"]), 1)
        self.assertEqual(kindle["intent"], "product_search")

        battery = self.ask("How long is the battery life of the Sony headphones?", self.cid, intent="clarification_needed")
        self.assertIn("30-hour", battery["_fake"].prompt_text())
        self.assertNotIn("clarify", battery["answer"].lower())

    def test_comparison_of_named_products(self):
        data = self.ask(
            "Compare Apple Watch Ultra 2 and the Classic Minimalist Chronograph Watch",
            self.cid, intent="product_comparison", category="Watches",
        )
        self.assertEqual(len(data["comparison"]["products"]), 2)

    def test_whole_catalog_sort(self):
        data = self.ask("Which is the cheapest product?", self.cid, sort_by="price_ascending")
        self.assertEqual(data["products"][0]["price"], "34.99")

    def test_unknown_products_are_not_invented(self):
        sofa = self.ask("Do you sell sofas?", self.cid, answer="The catalog has no sofas.", category="furniture", keywords=["sofa"])
        self.assertEqual(sofa["products"], [])
        samsung = self.ask("Which Samsung phones do you have?", self.cid, brand="Samsung", keywords=["phone"])
        self.assertEqual(samsung["products"], [])
        self.assertIn("Samsung", samsung["answer"])

    def test_descriptive_request_without_product_words_uses_meaning(self):
        data = self.ask(
            "Something to read books on the beach", self.cid,
            answer="The Kindle Paperwhite (16 GB) is great for reading on the beach.",
        )
        self.assertEqual(len(data["products"]), 1)
        self.assertTrue(data["products"][0]["title"].startswith("Kindle Paperwhite"))

    def test_quoted_greeting(self):
        data = self.ask('"Hello"', self.cid)
        self.assertIn("EcommerceAI", data["answer"])
        self.assertEqual(data["products"], [])

    def test_real_follow_up_still_works(self):
        first = self.ask("Show me fashion items under $150", category="Fashion", max_price=150)
        self.assertEqual(len(first["products"]), 2)
        second = self.ask("Increase my budget to 200", first["conversation_id"], max_price=200)
        self.assertEqual(len(second["products"]), 3)
        self.assertEqual(second["requirements"]["category"], "Fashion")


class AnswerTextTests(SimpleTestCase):
    def test_placeholder_link_lines_are_removed(self):
        from assistant.services.grounded_response_service import strip_empty_lines
        text = "**Nike**\n- Brand: Nike\n- Product link: [Not provided]\n- Product link:\n- Brand:\n- Product link: https://x.test/a"
        cleaned = strip_empty_lines(text)
        self.assertNotIn("Not provided", cleaned)
        self.assertNotIn("- Brand:\n", cleaned + "\n")
        self.assertIn("https://x.test/a", cleaned)

    def test_facts_answer_is_grounded(self):
        product = {"title": "X", "price": "10.00", "currency": "USD", "original_price": "12.00",
                   "is_available": False, "rating": 4.5, "review_count": 1200}
        text = facts_answer("price, stock and rating of X?", product)
        self.assertIn("10.00 USD", text)
        self.assertIn("out of stock", text)
        self.assertIn("4.5 from 1,200 reviews", text)
        self.assertIsNone(facts_answer("does it come in blue?", product))


class SemanticProbeCommandTests(ShopZoneBase):
    def test_prints_distances_nearest_first(self):
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        with patch_embeddings():
            call_command("semantic_probe", "read books beach", "--website-id", str(self.site.id), "--top", "3", stdout=out)
        lines = [l for l in out.getvalue().splitlines() if l.startswith("  ")]
        self.assertEqual(len(lines), 3)
        distances = [float(l.split()[0]) for l in lines]
        self.assertEqual(distances, sorted(distances))
