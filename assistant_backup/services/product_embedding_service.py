import hashlib

from assistant.models import ProductEmbedding
from assistant.services.embedding_service import EmbeddingService
from assistant.services.product_text_service import ProductTextService


class ProductEmbeddingService:
    """
    Generates and stores embeddings for product records.
    """

    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.product_text_service = ProductTextService()

    def needs_embedding(self, product):
        """True when the product has no embedding or its embedding text/model changed."""
        product_text = self.product_text_service.build_product_text(product)
        source_hash = hashlib.sha256(product_text.encode("utf-8")).hexdigest()
        existing = ProductEmbedding.objects.filter(product=product).first()
        return not (
            existing
            and existing.source_text_hash == source_hash
            and existing.embedding_model == self.embedding_service.model
        )

    def generate_for_product(self, product, force=False):
        """
        Generate or update the embedding for one product.

        If the source text has not changed, reuse the existing
        embedding unless force=True.
        """

        product_text = (
            self.product_text_service.build_product_text(product)
        )

        if not product_text.strip():
            raise ValueError(
                f"Product {product.pk} has no searchable text."
            )

        source_hash = hashlib.sha256(
            product_text.encode("utf-8")
        ).hexdigest()

        existing = ProductEmbedding.objects.filter(
            product=product
        ).first()

        if (
            existing
            and existing.source_text_hash == source_hash
            and existing.embedding_model == self.embedding_service.model
            and not force
        ):
            return existing

        vector = self.embedding_service.embed(product_text)

        embedding_record, _ = ProductEmbedding.objects.update_or_create(
            product=product,
            defaults={
                "embedding": vector,
                "source_text_hash": source_hash,
                "embedding_model": self.embedding_service.model,
            },
        )

        return embedding_record
    