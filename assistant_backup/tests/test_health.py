"""GET /api/health/ never calls a real Ollama in tests and never shows secrets."""
from unittest import mock

import requests
from django.test import TestCase
from rest_framework.test import APIClient


class HealthTests(TestCase):
    def get(self, ollama_side_effect=None, status_code=200):
        target = "assistant.health.requests.get"
        if ollama_side_effect:
            patcher = mock.patch(target, side_effect=ollama_side_effect)
        else:
            patcher = mock.patch(target, return_value=mock.Mock(status_code=status_code))
        with patcher as fake:
            response = APIClient().get("/api/health/")
        response.fake = fake
        return response

    def test_all_ok(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok", "ollama": "ok"})
        self.assertEqual(response.fake.call_args.kwargs["timeout"], 2)

    def test_ollama_down_is_degraded(self):
        response = self.get(requests.ConnectionError("refused at http://secret-host:11434"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "degraded", "database": "ok", "ollama": "unavailable"})
        self.assertNotIn("secret-host", response.content.decode())

    def test_database_down_is_503(self):
        with mock.patch("assistant.health.check_database", return_value="unavailable"):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")
