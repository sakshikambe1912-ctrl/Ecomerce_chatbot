import logging

import requests

from assistant.services.product_search_service import ProductSearchService
from assistant.services.semantic_search_service import SemanticSearchService

logger = logging.getLogger(__name__)


class HybridSearchService:
    """
    Combines structured product filtering with semantic relevance.

    ProductSearchService remains responsible for enforcing shopping
    constraints. SemanticSearchService contributes semantic ranking.
    """

    def __init__(self):
        self.product_search_service = ProductSearchService()
        self.semantic_search_service = SemanticSearchService()
        # False after a search in which semantic ranking could not be used
        # (for example Ollama is down). Results are then the structured order.
        self.semantic_available = True

    def search(
        self,
        requirements,
        website_ids,
        limit=10,
    ):
        if not website_ids:
            raise ValueError(
                "At least one website ID must be supplied."
            )

        if isinstance(website_ids, int):
            website_ids = [website_ids]
        else:
            website_ids = list(website_ids)

        if not website_ids:
            raise ValueError(
                "Website scope cannot be empty."
            )

        limit = max(1, min(limit, 100))

        # Step 1: Obtain products that satisfy structured requirements.
        filtered_products = self.product_search_service.search(
            requirements=requirements,
            website_ids=website_ids,
            limit=100,
        )

        if not filtered_products:
            return []

        # An explicit sort (price or rating) is the user's instruction; return
        # the structured order unchanged. Semantic blending is used only for
        # relevance ordering.
        sort_by = (
            requirements.get("sort_by", "relevance")
            if isinstance(requirements, dict)
            else requirements.sort_by
        )
        if sort_by != "relevance":
            return filtered_products[:limit]

        # Step 2: Retrieve semantic candidates from the selected websites.
        # Without any search terms there is nothing to rank semantically.
        query = self._build_query(requirements)
        if not query:
            return filtered_products[:limit]

        try:
            semantic_products = self.semantic_search_service.search(
                query=query,
                website_ids=website_ids,
                limit=100,
            )
        except (RuntimeError, requests.RequestException, ValueError) as exc:
            # Never fail the chat because embeddings are unavailable; keep the
            # structured results. Log the exception type only (no payloads).
            logger.warning("Semantic ranking unavailable (%s); using structured order.", type(exc).__name__)
            self.semantic_available = False
            return filtered_products[:limit]

        # Step 3: Create a map of semantic rankings.
        semantic_ranks = {
            product["id"]: rank
            for rank, product in enumerate(
                semantic_products,
                start=1,
            )
        }

        # Step 4: Preserve the structured-search results and use semantic
        # ranking only to improve their ordering.
        #
        # Products absent from the semantic candidate list remain eligible.
        # Their structured-search ranking is preserved as a fallback.
        structured_ranks = {
            product["id"]: rank
            for rank, product in enumerate(
                filtered_products,
                start=1,
            )
        }

        combined_products = []

        for product in filtered_products:
            product_id = product["id"]

            structured_rank = structured_ranks[product_id]
            semantic_rank = semantic_ranks.get(product_id)

            combined_score = 1.0 / (
                60 + structured_rank
            )

            if semantic_rank is not None:
                combined_score += 1.0 / (
                    60 + semantic_rank
                )

            combined_products.append(
                (combined_score, product)
            )

        # Step 5: Sort by the combined score.
        combined_products.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return [
            product
            for _, product in combined_products[:limit]
        ]

    @staticmethod
    def _build_query(requirements):
        """
        Build a descriptive query from the extracted requirements.
        """

        if isinstance(requirements, dict):
            from assistant.services.requirements_service import (
                ShoppingRequirements,
            )

            requirements = ShoppingRequirements.model_validate(
                requirements
            )

        terms = []

        if requirements.category:
            terms.append(requirements.category)

        terms.extend(requirements.keywords or [])
        terms.extend(requirements.must_have_features or [])

        if requirements.brand:
            terms.append(requirements.brand)

        return " ".join(
            dict.fromkeys(
                term.strip()
                for term in terms
                if isinstance(term, str) and term.strip()
            )
        )