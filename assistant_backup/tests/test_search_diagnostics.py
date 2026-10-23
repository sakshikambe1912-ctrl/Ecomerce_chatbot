"""No-match diagnostics: deterministic, names the blocking requirement."""
from django.test import TestCase

from assistant.services.product_search_service import ProductSearchService
from assistant.services.requirements_service import ShoppingRequirements
from assistant.services.search_diagnostics import build_no_match_message
from assistant.tests.factories import build_catalog, create_product


def req(**fields):
    fields.setdefault("keywords", [fields["category"]] if fields.get("category") else [])
    return ShoppingRequirements(**fields)


class DiagnosticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = build_catalog()
        cls.usd = cls.c["usd_site"].id

    def message(self, **fields):
        r = req(**fields)
        stages = ProductSearchService().diagnose(r, [self.usd])
        self.assertEqual(ProductSearchService().search(r, [self.usd]), [])
        return build_no_match_message(r, stages)

    def test_budget_too_low_names_budget_and_lowest_price(self):
        text = self.message(category="headphones", max_price=10, currency="USD")
        self.assertIn("8 products are in your selected websites", text)
        self.assertIn("6 match \"headphones\"", text)
        self.assertIn("none costs 10.00 USD or less", text)
        self.assertIn("The lowest price for headphones is 39.95 USD", text)
        self.assertIn("Raise your budget to at least 39.95 USD", text)

    def test_brand_not_available(self):
        text = self.message(category="headphones", brand="Nike")
        self.assertIn("none is from Nike", text)
        self.assertIn("Sony", text)

    def test_rating_too_high(self):
        text = self.message(category="headphones", min_rating=4.9)
        self.assertIn("none is rated 4.9 or higher", text)
        self.assertIn("The highest rating is 4.7", text)

    def test_unknown_category(self):
        self.assertIn("none matches \"television\"", self.message(category="television"))

    def test_feature_missing(self):
        text = self.message(category="laptop", must_have_features=["waterproof"])
        self.assertIn("none lists waterproof", text)

    def test_empty_website(self):
        empty = self.c["usd_site"].__class__.objects.create(name="Empty", base_url="https://empty.example.com")
        r = req(category="headphones")
        text = build_no_match_message(r, ProductSearchService().diagnose(r, [empty.id]))
        self.assertIn("no products yet", text)

    def test_short_alias_is_whole_word(self):
        create_product(self.c["usd_site"], title="Wireless Performance Mouse", category="Computers",
                       features=["Balanced weight"])
        results = ProductSearchService().search(req(must_have_features=["noise cancellation"], keywords=["mouse"]), [self.usd])
        self.assertNotIn("Wireless Performance Mouse", {r["title"] for r in results})
