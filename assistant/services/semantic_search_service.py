from pgvector.django import CosineDistance

from assistant.models import ProductEmbedding
from assistant.services.embedding_service import EmbeddingService
from assistant.services.product_search_service import product_to_dict


class SemanticSearchService:
    """
    Retrieves products by semantic similarity using PostgreSQL
    and pgvector.
    """

    def __init__(self):
        self.embedding_service = EmbeddingService()

    def search(
        self,
        query: str,
        website_ids: list[int] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Return products ranked by cosine similarity.

        If website_ids is provided, results are restricted to
        those websites.
        """

        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query must not be empty.")

        if limit < 1:
            raise ValueError("Limit must be greater than zero.")

        query_vector = self.embedding_service.embed(query)

        queryset = ProductEmbedding.objects.select_related(
            "product",
            "product__website",
        ).filter(
            product__website__is_active=True,
        )

        if website_ids is not None:
            if not website_ids:
                return []

            queryset = queryset.filter(
                product__website_id__in=website_ids,
            )

        queryset = queryset.order_by(
            CosineDistance("embedding", query_vector)
        )[:limit]

        results = []

        for record in queryset:
            product = record.product

            results.append(product_to_dict(product))

        return results

    def search_scored(self, query, website_ids=None, limit=10):
        """Like search(), but returns (product_dict, cosine_distance) pairs, nearest first.

        A smaller distance means a closer meaning. Used to decide how many of the
        nearest products are close enough to be worth showing.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query must not be empty.")
        if limit < 1:
            raise ValueError("Limit must be greater than zero.")

        query_vector = self.embedding_service.embed(query)

        queryset = ProductEmbedding.objects.select_related(
            "product", "product__website"
        ).filter(product__website__is_active=True)

        if website_ids is not None:
            if not website_ids:
                return []
            queryset = queryset.filter(product__website_id__in=website_ids)

        queryset = queryset.annotate(
            distance=CosineDistance("embedding", query_vector)
        ).order_by("distance")[:limit]

        return [(product_to_dict(r.product), float(r.distance)) for r in queryset]
