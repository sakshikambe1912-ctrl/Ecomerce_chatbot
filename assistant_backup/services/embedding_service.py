import requests
from django.conf import settings


class EmbeddingService:
    """
    Generates text embeddings using Ollama.
    """

    def __init__(self):
        self.base_url = getattr(
            settings,
            "OLLAMA_BASE_URL",
            "http://localhost:11434",
        ).rstrip("/")
        if self.base_url.endswith("/v1"):
          self.base_url = self.base_url[:-3]

        self.model = getattr(
            settings,
            "OLLAMA_EMBEDDING_MODEL",
            "nomic-embed-text",
        )

    def embed(self, text: str) -> list[float]:
        """
        Convert text into a numerical embedding vector.
        """

        if not isinstance(text, str) or not text.strip():
            raise ValueError("Text must not be empty.")

        try:
            response = requests.post(
                f"{self.base_url}/api/embed",
                json={
                    "model": self.model,
                    "input": text,
                },
                timeout=60,
            )

            response.raise_for_status()
            data = response.json()

        except requests.RequestException as exc:
            raise RuntimeError(
                f"Failed to generate embedding using Ollama: {exc}"
            ) from exc

        embeddings = data.get("embeddings")

        if not embeddings or not embeddings[0]:
            raise RuntimeError(
                "Ollama returned an empty embedding."
            )

        embedding = embeddings[0]

        if len(embedding) != 768:
            raise RuntimeError(
                f"Expected 768 embedding dimensions, "
                f"received {len(embedding)}."
            )

        return embedding