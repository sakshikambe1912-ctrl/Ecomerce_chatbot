"""GroundedResponseService: no LLM call without products; only supplied records reach the LLM."""
from django.test import SimpleTestCase

from assistant.services.grounded_response_service import GroundedResponseService
from assistant.tests.fakes import patch_llm

SONY = {"id": 1, "website_name": "Alpha Store", "title": "Sony WH-1000XM5", "brand": "Sony",
        "category": "Audio", "price": "328.00", "currency": "USD", "rating": 4.7,
        "is_available": True, "product_url": "", "features": [], "specifications": {}}
BOSE = dict(SONY, id=2, title="Bose QuietComfort", brand="Bose", price="279.00", rating=4.6)


class GroundedResponseTests(SimpleTestCase):
    def test_zero_products_returns_no_match_without_llm(self):
        with patch_llm() as fake:
            answer = GroundedResponseService().generate_answer("headphones", [])
        self.assertTrue(answer)
        self.assertEqual(fake.calls, [])

    def test_one_product_is_sent_to_llm(self):
        with patch_llm(["**Sony WH-1000XM5** - Price: 328.00 USD"]) as fake:
            answer = GroundedResponseService().generate_answer("headphones", [SONY])
        self.assertIn("Sony WH-1000XM5", answer)
        prompt = fake.prompt_text(0)
        self.assertIn("Sony WH-1000XM5", prompt)
        self.assertNotIn("Bose", prompt)

    def test_many_products_only_supplied_records(self):
        with patch_llm(["Two options."]) as fake:
            GroundedResponseService().generate_answer("headphones", [SONY, BOSE])
        prompt = fake.prompt_text(0)
        self.assertIn("Sony WH-1000XM5", prompt)
        self.assertIn("Bose QuietComfort", prompt)
        self.assertNotIn("Sennheiser", prompt)

    def test_empty_llm_output_raises(self):
        with patch_llm(["   "]):
            with self.assertRaises(ValueError):
                GroundedResponseService().generate_answer("headphones", [SONY])
