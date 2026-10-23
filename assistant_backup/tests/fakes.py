"""
Test doubles for the language model and the embedding service.

No test may call a live Ollama or Groq server. Every test that reaches a
model goes through FakeLLM / fake_embed via the patch helpers below.
"""
import hashlib
import importlib
import json
import math
import re
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest import mock

# Modules that construct an LLMService. Modules that do not exist yet are skipped.
LLM_MODULES = [
    "assistant.services.requirements_service",
    "assistant.services.grounded_response_service",
    "assistant.services.shopping_advice_service",
    "assistant.services.comparison_service",
]


class FakeLLM:
    """
    Stands in for LLMService. `responses` is a queue; each item is
    - a string (returned as the message content),
    - an exception instance (raised), or
    - a callable(kwargs) -> string.
    When the queue is empty, `default` is used (same kinds), else AssertionError.
    """

    def __init__(self, responses=None, default=None):
        self.responses = list(responses or [])
        self.default = default
        self.calls = []
        self.model = "fake-model"
        self.provider = "fake"
        self.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=self._create))
        )

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.responses:
            item = self.responses.pop(0)
        elif self.default is not None:
            item = self.default
        else:
            raise AssertionError("FakeLLM: no response queued for this call")
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))]
        )

    def generate_response(self, user_message):
        return self._create(messages=[{"role": "user", "content": user_message}]).choices[0].message.content

    # Helpers for assertions -------------------------------------------------
    def prompt_text(self, index=-1):
        call = self.calls[index]
        return "\n".join(m.get("content", "") for m in call.get("messages", []))

    def system_prompts(self):
        return [c["messages"][0]["content"] for c in self.calls if c.get("messages")]


def extraction(**fields):
    """JSON text an extraction call would return."""
    data = {
        "intent": "product_search",
        "keywords": [],
        "category": None,
        "brand": None,
        "min_price": None,
        "max_price": None,
        "currency": None,
        "min_rating": None,
        "only_available": True,
        "must_have_features": [],
        "sort_by": "relevance",
    }
    data.update(fields)
    return json.dumps(data)


def route(extraction_json=None, answer="Here are the matching products.", advice=None):
    """
    A callable response that answers extraction prompts with JSON and other
    prompts with prose, so a test does not depend on the number of calls.
    """
    extraction_json = extraction_json or extraction()

    def _respond(kwargs):
        system = kwargs.get("messages", [{}])[0].get("content", "").lower()
        if "extract" in system:
            return extraction_json
        if advice is not None and "general advice" in "\n".join(
            m.get("content", "") for m in kwargs.get("messages", [])
        ).lower():
            return advice
        return answer

    return _respond


@contextmanager
def patch_llm(responses=None, default=None):
    """Patch LLMService everywhere it is constructed. Yields the shared FakeLLM."""
    fake = FakeLLM(responses, default=default)
    with ExitStack() as stack:
        for name in LLM_MODULES:
            try:
                module = importlib.import_module(name)
            except ImportError:
                continue
            if hasattr(module, "LLMService"):
                stack.enter_context(mock.patch.object(module, "LLMService", return_value=fake))
        yield fake


def fake_embed(text):
    """Deterministic 768-dimensional unit vector; texts sharing words are similar."""
    words = re.findall(r"[a-z0-9]+", str(text).lower()) or ["empty"]
    vector = []
    for i in range(768):
        value = 0.0
        for word in words:
            digest = hashlib.md5(f"{word}:{i % 96}".encode()).digest()
            value += (digest[0] - 127.5) / 127.5
        vector.append(value)
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


@contextmanager
def patch_embeddings(side_effect=None):
    """Patch EmbeddingService.embed with fake_embed (or a given side effect)."""
    def _embed(self, text):
        if side_effect is not None:
            if isinstance(side_effect, BaseException):
                raise side_effect
            return side_effect(text)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Text must not be empty.")
        return fake_embed(text)

    with mock.patch(
        "assistant.services.embedding_service.EmbeddingService.embed",
        autospec=True,
        side_effect=_embed,
    ) as patched:
        yield patched


def embed_products(products):
    """Store fake embeddings for the given products."""
    from assistant.services.product_embedding_service import ProductEmbeddingService

    with patch_embeddings():
        service = ProductEmbeddingService()
        for product in products:
            service.generate_for_product(product, force=True)
