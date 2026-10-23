"""ComparisonService and alternatives: computed in code, never presented as matches."""
from assistant.services.alternatives_service import INTRO, find_alternatives
from assistant.services.comparison_service import build_comparison, is_comparison_request, render_comparison
from assistant.services.product_search_service import product_to_dict
from assistant.services.requirements_service import ShoppingRequirements
from assistant.tests.fakes import extraction, route
from assistant.tests.test_chat_api import ChatAPITestBase


def req(**fields):
    return ShoppingRequirements(**{"category": "headphones", "keywords": ["headphones"], "currency": "USD", **fields})


class BuildComparisonTests(ChatAPITestBase):
    def dicts(self, *names):
        return [product_to_dict(self.c[n]) for n in names]

    def facts(self, comparison):
        return {(f["kind"], f["currency"]): f for f in comparison["facts"]}

    def test_rows_and_facts_same_currency(self):
        comparison = build_comparison(self.dicts("sony_xm5", "bose_qc", "jbl_tune"))
        self.assertEqual(len(comparison["products"]), 3)
        row = comparison["products"][0]
        for key in ("price", "currency", "rating", "review_count", "is_available", "key_features", "website_name"):
            self.assertIn(key, row)
        facts = self.facts(comparison)
        self.assertEqual(facts[("cheapest", "USD")]["titles"], ["JBL Tune 510BT On-Ear Headphones"])
        self.assertEqual(facts[("cheapest", "USD")]["value"], "39.95")
        self.assertEqual(facts[("best_rated", "USD")]["value"], 4.7)
        self.assertEqual(facts[("most_reviewed", "USD")]["value"], 9800)

    def test_different_currencies_are_never_compared(self):
        comparison = build_comparison(self.dicts("sony_xm5", "sony_inr"))
        self.assertEqual(comparison["facts"], [])
        self.assertIn("different currencies", comparison["notes"][0])

    def test_stale_website_blocks_cross_site_price_fact(self):
        other = self.c["usd_site"].__class__.objects.create(name="Gamma", base_url="https://gamma.example.com")
        from assistant.tests.factories import create_product

        cheap = product_to_dict(create_product(other, title="Gamma Headphones", price="20.00", rating="3.9"))
        products = self.dicts("sony_xm5") + [cheap]
        fresh = self.facts(build_comparison(products))
        self.assertIn(("cheapest", "USD"), fresh)
        stale = build_comparison(products, stale_website_ids=[other.id])
        self.assertNotIn(("cheapest", "USD"), self.facts(stale))
        self.assertIn(("best_rated", "USD"), self.facts(stale))
        self.assertIn("Gamma", stale["notes"][0])

    def test_ties_name_every_winner(self):
        comparison = build_comparison(self.dicts("sony_xm5", "unavailable", "macbook"))
        best = self.facts(comparison)[("best_rated", "USD")]
        self.assertEqual(len(best["product_ids"]), 2)

    def test_single_product_is_not_a_comparison(self):
        self.assertIsNone(build_comparison(self.dicts("sony_xm5")))

    def test_render_uses_only_record_values(self):
        text = render_comparison(build_comparison(self.dicts("sony_xm5", "jbl_tune")))
        self.assertIn("328.00 USD", text)
        self.assertIn("Cheapest (USD): JBL Tune 510BT On-Ear Headphones at 39.95 USD", text)

    def test_comparison_questions_detected(self):
        for message in ("which is cheapest?", "Which one has the best rating", "compare them", "Sony vs Bose"):
            self.assertTrue(is_comparison_request(req(), message), message)
        self.assertFalse(is_comparison_request(req(), "headphones under $350"))
        self.assertTrue(is_comparison_request(req(intent="product_comparison"), "these two"))


class AlternativesTests(ChatAPITestBase):
    def test_strict_budget_miss_is_an_alternative_not_a_match(self):
        data = self.chat("Sennheiser headphones under $350", llm=route(
            extraction(category="headphones", keywords=["headphones"], brand="Sennheiser", max_price=350,
                       currency="USD"))).json()
        self.assertEqual(data["products"], [])
        self.assertEqual([a["title"] for a in data["alternatives"]], ["Sennheiser Momentum 4 Wireless Headphones"])
        self.assertIn("above your budget of 350.00 USD", data["alternatives"][0]["unmet"][0])
        self.assertIn(INTRO, data["answer"])
        self.assertNotIn(self.c["sennheiser"].id, [p["id"] for p in data["products"]])

    def test_more_than_fifteen_percent_over_budget_is_not_offered(self):
        alternatives = find_alternatives(req(brand="Sennheiser", max_price=300), [self.usd])
        self.assertEqual(alternatives, [])

    def test_lower_rated_alternatives_capped_at_three(self):
        alternatives = find_alternatives(req(max_price=350, min_rating=4.7), [self.usd],
                                         exclude_ids=[self.c["sony_xm5"].id])
        self.assertEqual(len(alternatives), 3)
        self.assertTrue(all(a["unmet"][0].startswith("Rated ") for a in alternatives))
        self.assertNotIn(self.c["unavailable"].id, [a["id"] for a in alternatives])  # availability never relaxed

    def test_missing_feature_alternative(self):
        alternatives = find_alternatives(req(max_price=100, must_have_features=["noise cancellation"]), [self.usd])
        self.assertTrue(alternatives)
        self.assertTrue(all(a["unmet"] == ["Does not list noise cancellation"] for a in alternatives))
        self.assertTrue(all(float(a["price"]) <= 100 for a in alternatives))

    def test_brand_currency_and_scope_never_relaxed(self):
        alternatives = find_alternatives(req(brand="Bose", min_rating=4.7), [self.usd, self.inr])
        self.assertEqual({a["brand"] for a in alternatives}, {"Bose"})
        self.assertEqual({a["currency"] for a in alternatives}, {"USD"})
        self.assertEqual(find_alternatives(req(brand="Sony", max_price=50), [self.usd]), [])

    def test_alternatives_fail_exactly_one_requirement(self):
        # Sennheiser is over budget AND below the rating, so it is not an alternative.
        alternatives = find_alternatives(req(max_price=350, min_rating=4.7), [self.usd])
        self.assertNotIn(self.c["sennheiser"].id, [a["id"] for a in alternatives])

    def test_enough_matches_means_no_alternatives(self):
        data = self.chat("Suggest headphones under $350").json()
        self.assertGreaterEqual(len(data["products"]), 3)
        self.assertEqual(data["alternatives"], [])


class ComparisonChatTests(ChatAPITestBase):
    def test_which_is_cheapest_uses_computed_comparison(self):
        data = self.chat("which is the cheapest of these headphones under $350?", llm=route(
            HEADPHONES_350, answer="**JBL Tune 510BT On-Ear Headphones** is the cheapest at 39.95 USD.")).json()
        cheapest = [f for f in data["comparison"]["facts"] if f["kind"] == "cheapest"][0]
        self.assertEqual(cheapest["value"], "39.95")
        self.assertIn("39.95 USD", data["answer"])

    def test_invented_value_in_explanation_falls_back_to_computed_text(self):
        data = self.chat("compare these headphones under $350", llm=route(
            HEADPHONES_350, answer="The JBL is cheapest at 19.99 USD with rating 5.0.")).json()
        self.assertNotIn("19.99", data["answer"])
        self.assertIn("Comparison of the current results:", data["answer"])

    def test_plain_search_has_no_comparison(self):
        data = self.chat("Suggest headphones under $350").json()
        self.assertIsNone(data["comparison"])


HEADPHONES_350 = extraction(category="headphones", keywords=["headphones"], max_price=350, currency="USD")


class ExplanationGuardTests(ChatAPITestBase):
    def test_explanation_naming_no_product_is_replaced(self):
        data = self.chat("compare these headphones under $350", llm=route(
            HEADPHONES_350, answer="General shopping advice.")).json()
        self.assertIn("Comparison of the current results:", data["answer"])
