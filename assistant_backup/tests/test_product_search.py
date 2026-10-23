"""ProductSearchService: hard filters, matching and sorting."""
from django.test import TestCase

from assistant.services.product_search_service import ProductSearchService
from assistant.services.requirements_service import ShoppingRequirements
from assistant.tests.factories import build_catalog, create_product, create_website


def req(**fields):
    fields.setdefault("keywords", [fields["category"]] if fields.get("category") else [])
    return ShoppingRequirements(**fields)


class ProductSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = build_catalog()
        cls.usd = cls.c["usd_site"].id
        cls.inr = cls.c["inr_site"].id

    def search(self, website_ids=None, **fields):
        return ProductSearchService().search(req(**fields), website_ids or [self.usd])

    def ids(self, results):
        return {r["id"] for r in results}

    # ---- scope -------------------------------------------------------------
    def test_results_stay_inside_selected_website(self):
        results = self.search(category="headphones")
        self.assertTrue(results)
        self.assertTrue(all(r["website_id"] == self.usd for r in results))

    def test_inactive_website_is_excluded(self):
        closed = create_website("Closed Shop", active=False)
        create_product(closed, title="Closed Shop Wireless Headphones", category="Audio")
        results = self.search([self.usd, closed.id], category="headphones")
        self.assertNotIn(closed.id, {r["website_id"] for r in results})

    def test_multi_website_returns_both_sites(self):
        results = self.search([self.usd, self.inr], category="headphones")
        self.assertEqual({r["website_id"] for r in results}, {self.usd, self.inr})

    def test_requires_a_website(self):
        with self.assertRaises(ValueError):
            ProductSearchService().search(req(category="headphones"), [])

    # ---- price, currency, rating, availability -----------------------------
    def test_max_price(self):
        results = self.search(category="headphones", max_price=300)
        self.assertEqual(
            self.ids(results),
            {self.c["bose_qc"].id, self.c["jbl_tune"].id, self.c["sony_noname"].id},
        )

    def test_min_price(self):
        results = self.search(category="headphones", min_price=300)
        self.assertEqual(self.ids(results), {self.c["sony_xm5"].id, self.c["sennheiser"].id})

    def test_currency_filter(self):
        results = self.search([self.usd, self.inr], category="headphones", currency="INR")
        self.assertTrue(results)
        self.assertTrue(all(r["currency"] == "INR" for r in results))

    def test_min_rating(self):
        results = self.search(category="headphones", min_rating=4.6)
        self.assertEqual(self.ids(results), {self.c["sony_xm5"].id, self.c["bose_qc"].id})

    def test_only_available_excludes_unavailable(self):
        results = self.search(category="headphones", only_available=True)
        self.assertNotIn(self.c["unavailable"].id, self.ids(results))

    def test_only_available_false_includes_unavailable(self):
        results = self.search(category="headphones", only_available=False)
        self.assertIn(self.c["unavailable"].id, self.ids(results))

    # ---- category, brand, features -----------------------------------------
    def test_category_laptop(self):
        self.assertEqual(self.ids(self.search(category="laptop")), {self.c["macbook"].id})

    def test_category_power_bank(self):
        self.assertEqual(self.ids(self.search(category="power bank")), {self.c["anker"].id})

    def test_brand_filter_is_case_insensitive(self):
        results = self.search(category="headphones", brand="sony")
        self.assertIn(self.c["sony_xm5"].id, self.ids(results))
        self.assertNotIn(self.c["bose_qc"].id, self.ids(results))

    def test_brand_matches_title_when_brand_field_empty(self):
        results = self.search(category="headphones", brand="Sony")
        self.assertIn(self.c["sony_noname"].id, self.ids(results))

    def test_brand_requires_whole_word(self):
        store = self.c["usd_site"]
        create_product(store, title="Sonya Brand Wireless Headphones", brand="", category="Audio")
        results = self.search(category="headphones", brand="Sony")
        self.assertNotIn("Sonya Brand Wireless Headphones", {r["title"] for r in results})

    def test_required_feature_with_aliases(self):
        results = self.search(category="headphones", must_have_features=["noise cancellation"])
        self.assertEqual(
            self.ids(results),
            {self.c["sony_xm5"].id, self.c["bose_qc"].id, self.c["sennheiser"].id},
        )

    # ---- sorting -----------------------------------------------------------
    def prices(self, results):
        return [float(r["price"]) for r in results]

    def test_sort_price_ascending(self):
        prices = self.prices(self.search(category="headphones", sort_by="price_ascending"))
        self.assertEqual(prices, sorted(prices))

    def test_sort_price_descending(self):
        prices = self.prices(self.search(category="headphones", sort_by="price_descending"))
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_sort_rating(self):
        ratings = [r["rating"] for r in self.search(category="headphones", sort_by="rating")]
        self.assertEqual(ratings, sorted(ratings, reverse=True))

    def test_sort_relevance_puts_category_matches_first(self):
        results = self.search(category="headphones", sort_by="relevance")
        self.assertTrue(all("headphones" in r["title"].lower() for r in results))

    # ---- empty and output shape --------------------------------------------
    def test_empty_result(self):
        self.assertEqual(self.search(category="television"), [])

    def test_result_contains_api_contract_fields(self):
        result = self.search(category="laptop")[0]
        for key in ("id", "website_id", "website_name", "title", "brand", "category", "description",
                    "price", "original_price", "currency", "rating", "review_count", "is_available",
                    "product_url", "image_url", "features", "specifications", "last_fetched_at"):
            self.assertIn(key, result)
