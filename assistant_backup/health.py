"""GET /api/health/ — database and Ollama reachability, with no secrets or URLs."""
import logging

import requests
from django.conf import settings
from django.db import connection
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
OLLAMA_TIMEOUT_SECONDS = 2


def check_database():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return "ok"
    except Exception as exc:  # report the state, never the error text
        logger.warning("Health check: database unavailable (%s).", type(exc).__name__)
        return "unavailable"


def check_ollama():
    # The OpenAI-compatible URL ends in /v1; Ollama's own root answers a plain GET.
    base = settings.OLLAMA_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    try:
        response = requests.get(base + "/", timeout=OLLAMA_TIMEOUT_SECONDS)
        return "ok" if response.status_code < 500 else "unavailable"
    except requests.RequestException as exc:
        logger.info("Health check: Ollama unreachable (%s).", type(exc).__name__)
        return "unavailable"


class HealthAPIView(APIView):
    authentication_classes = []

    def get(self, request):
        database = check_database()
        ollama = check_ollama()
        if database != "ok":
            status = "error"
        elif ollama != "ok":
            status = "degraded"  # chat with Groq still works; embeddings need Ollama
        else:
            status = "ok"
        return Response({"status": status, "database": database, "ollama": ollama},
                        status=503 if status == "error" else 200)
