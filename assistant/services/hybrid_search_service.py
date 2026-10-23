import logging

import requests
from django.conf import settings

from assistant.services.product_search_service import ProductSearchService
from assistant.services.semantic_search_service import SemanticSearchService

logger = logging.getLogger(__name__)

SEMANTIC_ERRORS = (RuntimeError, requests.RequestException, ValueError)


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
        # "structured": every result matched the request's words.
        # "semantic": results were chosen by meaning (closest matches only).
        self.mode = "structured"

    def search(
        self,
        requirements,
        website_ids,
        limit=10,
        query_text=None,
    ):
        """
        `query_text` is the user's own message. When given, it is used for the
        semantic part, so a wrong keyword extraction cannot hide the right product.
        """
        self.mode = "structured"
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

        query_text = (query_text or "").strip() or None
        shopping = self._as_requirements(requirements)

        if not filtered_products:
            # Nothing matched the request's words. If that is because the product
            # type is unknown to this catalog (the model used a different word,
            # for example "footwear" for shoes), choose by meaning instead. If the
            # type exists and only a budget/rating/stock limit removed it, the
            # honest answer is "nothing matches", so return nothing.
            if (
                query_text
                and self._has_topic(shopping)
                and shopping.sort_by == "relevance"
                and not self._topic_exists(shopping, website_ids)
            ):
                hard_only = shopping.model_copy(update={"category": None, "keywords": []})
                candidates = self.product_search_service.search(
                    requirements=hard_only, website_ids=website_ids, limit=100,
                )
                return self._rank_by_meaning(candidates, website_ids, query_text, limit)
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

        # A descriptive request with no product words at all ("something to read
        # on the beach"): keep only the products closest in meaning.
        if query_text and not self._has_topic(shopping):
            return self._rank_by_meaning(filtered_products, website_ids, query_text, limit)

        if not query:
            return filtered_products[:limit]
        query = query_text or query

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
    def _as_requirements(requirements):
        from assistant.services.requirements_service import ShoppingRequirements

        if isinstance(requirements, dict):
            return ShoppingRequirements.model_validate(requirements)
        return requirements

    @staticmethod
    def _has_topic(requirements):
        return bool(
            requirements.category
            or requirements.keywords
            or requirements.must_have_features
            or requirements.brand
        )

    def _topic_exists(self, requirements, website_ids):
        """True if some product matches the request's words, ignoring budget, rating and stock."""
        topic_only = requirements.model_copy(update={
            "min_price": None, "max_price": None, "min_rating": None,
            "currency": None, "only_available": False,
        })
        return bool(self.product_search_service.search(
            requirements=topic_only, website_ids=website_ids, limit=1,
        ))

    def _rank_by_meaning(self, candidates, website_ids, query_text, limit):
        """
        Keep only the candidates closest in meaning to the user's message:
        within SEMANTIC_MARGIN of the closest one, at most SEMANTIC_FALLBACK_LIMIT,
        and (if set) below SEMANTIC_MAX_DISTANCE. Returns [] if embeddings are down.
        """
        if not candidates:
            return []
        try:
            scored = self.semantic_search_service.search_scored(
                query=query_text, website_ids=website_ids, limit=100,
            )
        except SEMANTIC_ERRORS as exc:
            logger.warning("Semantic search unavailable (%s).", type(exc).__name__)
            self.semantic_available = False
            return []

        allowed = {product["id"]: product for product in candidates}
        scored = [(allowed[p["id"]], d) for p, d in scored if p["id"] in allowed]
        if not scored:
            return []

        margin = getattr(settings, "SEMANTIC_MARGIN", 0.08)
        ceiling = getattr(settings, "SEMANTIC_MAX_DISTANCE", 0.0)
        cap = getattr(settings, "SEMANTIC_FALLBACK_LIMIT", 5)
        best = scored[0][1]
        kept = [
            product for product, distance in scored
            if distance <= best + margin and (not ceiling or distance <= ceiling)
        ]
        self.mode = "semantic"
        return kept[: max(1, min(limit, cap))]

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