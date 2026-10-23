"""Deterministic scope guard (runs before any model call)."""
from django.test import SimpleTestCase

from assistant.services.scope_guard import check


class ScopeGuardTests(SimpleTestCase):
    def test_out_of_scope_requests(self):
        for message in ("write a python script to sort a list", "Write me an essay about rivers",
                        "translate this sentence to French", "build me a website", "a poem about cats"):
            self.assertEqual(check(message), "out_of_scope", message)

    def test_shopping_words_keep_requests_in_scope(self):
        for message in ("laptop for python programming", "do you have a discount code",
                        "headphones under $350", "compare these two phones", "cheapest keyboard for coding"):
            self.assertIsNone(check(message), message)

    def test_greetings(self):
        for message in ("hello", "Hi there!", "good morning", "hey, what can you do?"):
            self.assertEqual(check(message), "greeting", message)
        self.assertIsNone(check("hello, show me headphones"))
