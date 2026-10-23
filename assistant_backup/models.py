from django.db import models
from pgvector.django import VectorField
class ProductEmbedding(models.Model):
    """
    Stores vector embeddings for products separately
    from the existing Product model.
    """

    product = models.OneToOneField(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="embedding_record",
    )

    embedding = VectorField(dimensions=768)

    source_text_hash = models.CharField(
        max_length=64,
        blank=True,
    )

    embedding_model = models.CharField(
        max_length=100,
        default="nomic-embed-text",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assistant_product_embeddings"

    def __str__(self):
        return f"Embedding for product {self.product_id}"
