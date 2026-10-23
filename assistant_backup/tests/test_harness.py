"""Checks that the test helpers themselves behave as documented."""
from django.test import TestCase

from assistant.tests.factories import build_catalog
from assistant.tests.fakes import FakeLLM, fake_embed, patch_embeddings, patch_llm


class HarnessTests(TestCase):
    def test_catalog_has_two_currencies(self):
        c = build_catalog()
        self.assertEqual(c["usd_site"].products.first().currency, "USD")
        self.assertEqual(c["inr_site"].products.first().currency, "INR")

    def test_fake_llm_queue_and_errors(self):
        llm = FakeLLM(["first", ValueError("boom")])
        out = llm.client.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
        self.assertEqual(out.choices[0].message.content, "first")
        with self.assertRaises(ValueError):
            llm.client.chat.completions.create(model="m", messages=[])
        self.assertEqual(len(llm.calls), 2)

    def test_patch_llm_replaces_service(self):
        from assistant.services.requirements_service import RequirementsService

        with patch_llm(["{}"]) as fake:
            self.assertIs(RequirementsService().llm_service, fake)

    def test_fake_embed_is_deterministic_768(self):
        a, b = fake_embed("sony headphones"), fake_embed("sony headphones")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 768)

    def test_patch_embeddings(self):
        from assistant.services.embedding_service import EmbeddingService

        with patch_embeddings():
            self.assertEqual(len(EmbeddingService().embed("laptop")), 768)
