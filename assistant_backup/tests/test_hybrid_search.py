"""HybridSearchService: semantic ranking may only reorder structured results."""
from unittest import mock

from django.test import TestCase

from assistant.services.hybrid_search_service import HybridSearchService
from assistant.services.product_search_service import ProductSearchService
from assistant.services.requirements_service import ShoppingRequirements
from assistant.tests.factories import build_catalog
from assistant.tests.fakes import embed_products, patch_embeddings
from products.models import Product


def req(**fields):
    fields.setdefault("keywords", [fields["category"]] if fields.get("category") else [])
    return ShoppingRequirements(**fields)


class HybridSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = build_catalog()
        cls.usd = cls.c["usd_site"].id
        cls.inr = cls.c["inr_site"].id
        embed_products(Product.objects.all())

    def hybrid(self, requirements, website_ids):
        with patch_embeddings():
            return HybridSearchService().search(requirements, website_ids, limit=20)

    def structured(self, requirements, website_ids):
        return ProductSearchService().search(requirements, website_ids, limit=100)

    def test_results_are_a_subset_of_structured_results(self):
        r = req(category="headphones", max_price=300)
        hybrid_ids = {p["id"] for p in self.hybrid(r, [self.usd])}
        structured_ids = {p["id"] for p in self.structured(r, [self.usd])}
        self.assertTrue(hybrid_ids)
        self.assertLessEqual(hybrid_ids, structured_ids)

    def test_semantic_ranking_only_reorders(self):
        r = req(category="headphones")
        self.assertEqual(
            sorted(p["id"] for p in self.hybrid(r, [self.usd])),
            sorted(p["id"] for p in self.structured(r, [self.usd])),
        )

    def test_every_result_belongs_to_selected_websites(self):
        for scope in ([self.usd], [self.inr], [self.usd, self.inr]):
            results = self.hybrid(req(category="headphones"), scope)
            self.assertTrue(results)
            self.assertTrue(all(p["website_id"] in scope for p in results))

    def test_no_structured_results_means_no_results(self):
        self.assertEqual(self.hybrid(req(category="headphones", max_price=1), [self.usd]), [])

    def test_semantic_failure_falls_back_to_structured(self):
        r = req(category="headphones")
        with patch_embeddings(side_effect=RuntimeError("Ollama down")):
            results = HybridSearchService().search(r, [self.usd], limit=20)
        self.assertEqual([p["id"] for p in results], [p["id"] for p in self.structured(r, [self.usd])][:20])

    def test_explicit_sort_is_not_reordered_by_semantics(self):
        r = req(category="headphones", sort_by="price_ascending")
        structured = self.structured(r, [self.usd])
        most_expensive = structured[-1]
        # Make semantics strongly prefer the most expensive item.
        with mock.patch(
            "assistant.services.semantic_search_service.SemanticSearchService.search",
            return_value=[most_expensive],
        ), patch_embeddings():
            results = HybridSearchService().search(r, [self.usd], limit=20)
        self.assertEqual([p["id"] for p in results], [p["id"] for p in structured])


class ProductTextTests(TestCase):
    def test_price_only_change_keeps_embedding_text(self):
        from assistant.services.product_text_service import ProductTextService
        from assistant.tests.factories import create_product, create_website

        product = create_product(create_website("Text Store"), title="Sony Headphones", price="100.00", rating="4.1")
        before = ProductTextService().build_product_text(product)
        product.price, product.rating, product.currency = 250, 4.9, "INR"
        self.assertEqual(ProductTextService().build_product_text(product), before)
        self.assertNotIn("100", before)
