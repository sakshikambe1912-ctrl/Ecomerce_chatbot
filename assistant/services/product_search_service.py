import re
from decimal import Decimal

from products.models import Product
from assistant.services.requirements_service import (
    ShoppingRequirements,
)


def _word_pattern(text):
    """Whole-word, case-insensitive match that also works for brands like 'Audio-Technica'."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(text.strip().lower()) + r"(?![a-z0-9])")


# Filler words that must never decide whether a product matches.
KEYWORD_STOPWORDS = {
    "show", "me", "find", "get", "give", "search", "looking", "look", "for",
    "want", "need", "buy", "suggest", "recommend", "please", "some", "any",
    "a", "an", "the", "i", "my", "to", "of", "and", "or", "with", "in", "on",
    "do", "you", "have", "sell", "is", "there", "are", "something", "can",
}


def _singular(word):
    """Very small singular form: shoes -> shoe, watches -> watch, batteries -> battery."""
    word = word.strip().lower()
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "xes", "sses", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _variants(term):
    """The term and its singular form (the singular also matches the plural in text)."""
    term = term.strip().lower()
    return list(dict.fromkeys([term, " ".join(_singular(w) for w in term.split())]))


def _plural_word_pattern(word):
    """Whole word, optionally plural: 'shoe' matches 'shoe', 'shoes'."""
    base = re.escape(_singular(word))
    return re.compile(r"(?<![a-z0-9])" + base + r"(?:s|es)?(?![a-z0-9])")


def _feature_key(feature):
    """'noise_cancellation' and 'noise-cancellation' both become 'noise cancellation'."""
    return re.sub(r"[_\-\s]+", " ", feature.strip().lower())


def brand_matches(product, requested):
    """
    Brand rule (case-insensitive, whole word):
    - if the product has a brand, the requested brand must match it;
    - if the brand field is empty, the requested brand must appear in the title.
    """
    if not requested or not requested.strip():
        return True
    pattern = _word_pattern(requested)
    brand = (product.brand or "").strip().lower()
    if brand:
        return bool(pattern.search(brand))
    return bool(pattern.search((product.title or "").lower()))


def _number(value):
    return float(value) if value is not None else None


def product_to_dict(product):
    """The Product object returned by every API (see the API contract)."""
    return {
        "id": product.id,
        "website_id": product.website_id,
        "website_name": product.website.name,
        "title": product.title,
        "brand": product.brand,
        "category": product.category,
        "description": product.description,
        "price": str(product.price),
        "original_price": str(product.original_price) if product.original_price is not None else None,
        "currency": product.currency,
        "rating": _number(product.rating),
        "review_count": product.review_count,
        "is_available": product.is_available,
        "product_url": product.product_url,
        "image_url": product.image_url,
        "features": product.features,
        "specifications": product.specifications,
        "last_fetched_at": product.last_fetched_at.isoformat() if product.last_fetched_at else None,
    }


# Common variations of feature names.
FEATURE_ALIASES = {
    "wireless connectivity": [
        "wireless",
        "bluetooth",
    ],
    "wireless": [
        "wireless",
        "bluetooth",
    ],
    "bluetooth connectivity": [
        "bluetooth",
    ],
    "noise cancellation": [
        "noise cancellation",
        "noise cancelling",
        "noise-cancelling",
        "noise canceling",
        "noise-canceling",
        "active noise cancellation",
        "active noise cancelling",
        "active noise canceling",
        "anc",
    ],
    "noise cancelling": [
        "noise cancellation",
        "noise cancelling",
        "noise-cancelling",
        "noise canceling",
        "noise-canceling",
        "active noise cancellation",
        "active noise cancelling",
        "active noise canceling",
        "anc",
    ],
    "water resistant": [
        "water resistant",
        "water-resistant",
        "water resistance",
    ],
    "waterproof": [
        "waterproof",
        "water proof",
    ],
    "long battery life": [
        "long battery life",
        "extended battery life",
        "longer battery life",
        "hours of battery life",
    ],
    "fast charging": [
        "fast charging",
        "quick charging",
        "rapid charging",
    ],
    "portable": [
        "portable",
        "compact",
    ],
    "high battery capacity": [
        "high battery capacity",
        "large battery capacity",
        "huge battery capacity",
        "high capacity",
        "large capacity",
        "huge capacity",
        "mah capacity",
    ],
    "high capacity": [
        "high capacity",
        "large capacity",
        "huge capacity",
        "mah capacity",
    ],
    "multi-device connectivity": [
        "multipoint",
        "multi-device",
        "multiple devices",
        "multiple-device",
    ],
}


def _text_of(value):
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value)
    return str(value or "")


def searchable_fields(product):
    """Lower-cased text fields of a product used for matching."""
    fields = {
        "title": (product.title or "").lower(),
        "category": (product.category or "").lower(),
        "brand": (product.brand or "").lower(),
        "description": (product.description or "").lower(),
        "features": _text_of(getattr(product, "features", None)).lower(),
        "specifications": _text_of(getattr(product, "specifications", None)).lower(),
    }
    fields["text"] = " ".join(fields.values())
    return fields


def category_matches(fields, requested_category):
    """The requested product type may appear in the category, title, description or metadata."""
    keys = ("category", "title", "description", "features", "specifications")
    return any(
        variant in fields[key]
        for variant in _variants(requested_category)
        for key in keys
    )


def _alias_in(alias, text):
    # Short aliases such as "anc" must be whole words ("performance" is not ANC).
    if len(alias) <= 4:
        return bool(_word_pattern(alias).search(text))
    return alias in text


def features_match(fields, features):
    """Every requested feature (or one of its aliases) must appear in the product text."""
    return all(
        any(
            _alias_in(alias, fields["text"])
            for alias in FEATURE_ALIASES.get(_feature_key(feature), [_feature_key(feature)])
        )
        for feature in features
    )


class ProductSearchService:

    def search(self, requirements, website_ids, limit=20):

        # --------------------------------------------------
        # 1. Validate website scope
        # --------------------------------------------------

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

        website_ids = list(set(website_ids))
        limit = max(1, min(limit, 100))

        # --------------------------------------------------
        # 2. Retrieve products from selected active websites
        # --------------------------------------------------

        queryset = Product.objects.filter(
            website_id__in=website_ids,
            website__is_active=True,
        ).select_related("website")

        if isinstance(requirements, dict):
            requirements = ShoppingRequirements.model_validate(
                requirements
            )

        # --------------------------------------------------
        # 3. Apply hard constraints
        #
        # These filters must never be silently relaxed.
        # --------------------------------------------------

        if requirements.only_available:
            queryset = queryset.filter(is_available=True)

        if requirements.min_price is not None:
            queryset = queryset.filter(
                price__gte=requirements.min_price
            )

        if requirements.max_price is not None:
            queryset = queryset.filter(
                price__lte=requirements.max_price
            )

        if requirements.min_rating is not None:
            queryset = queryset.filter(
                rating__gte=requirements.min_rating
            )

        # Never compare prices in different currencies.
        if requirements.currency:
            queryset = queryset.filter(
                currency__iexact=requirements.currency
            )

        # --------------------------------------------------
        # 4. Load products that satisfy hard constraints
        # --------------------------------------------------

        products = list(queryset)

        # --------------------------------------------------
        # 5. Prepare search terms
        # --------------------------------------------------

        keywords = [
            keyword.strip().lower()
            for keyword in requirements.keywords
            if keyword and keyword.strip()
        ]

        features = [
            _feature_key(feature)
            for feature in requirements.must_have_features
            if feature and feature.strip()
        ]

        requested_brand = (
            requirements.brand.strip().lower()
            if requirements.brand
            else None
        )

        requested_category = (
            requirements.category.strip().lower()
            if requirements.category
            else None
        )

        # --------------------------------------------------
        # 7. Score and filter products
        # --------------------------------------------------

        scored_products = []
        relevance_by_id = {}

        for product in products:

            fields = searchable_fields(product)
            title = fields["title"]
            category = fields["category"]
            brand = fields["brand"]
            description = fields["description"]
            product_text = fields["text"]

            # Brand, category and required features are hard constraints.
            if requested_brand and not brand_matches(product, requested_brand):
                continue

            category_match = False
            if requested_category:
                category_match = category_matches(fields, requested_category)
                if not category_match:
                    continue

            if features and not features_match(fields, features):
                continue

            # ----------------------------------------------
            # Initialize relevance score
            # ----------------------------------------------

            # `relevance` counts only real text matches. The rating bonus below
            # is for ordering and must never make an unrelated product relevant.
            relevance = 0

            # ----------------------------------------------
            # Keyword relevance
            # ----------------------------------------------

            for keyword in keywords:
                variants = _variants(keyword)

                if any(v in title for v in variants):
                    relevance += 5

                elif any(v in category for v in variants):
                    relevance += 4

                elif any(v in brand for v in variants):
                    relevance += 3

                elif any(v in description for v in variants):
                    relevance += 2

                elif any(v in product_text for v in variants):
                    relevance += 1

                else:
                    # Partial phrase match on whole words, ignoring filler
                    # words such as "show me".
                    words = [
                        w for w in keyword.split()
                        if w not in KEYWORD_STOPWORDS and len(w) > 2
                    ]
                    matched_words = sum(
                        1
                        for word in words
                        if _plural_word_pattern(word).search(product_text)
                    )
                    if words:
                        relevance += matched_words / len(words)

            # Required features were validated above.
            if features:
                relevance += 3 * len(features)

            if category_match:
                relevance += 4

            relevance_by_id[product.id] = relevance
            score = relevance

            # Rating bonus: ordering only.
            if (
                requirements.sort_by == "relevance"
                and product.rating is not None
            ):
                score += float(product.rating) * 0.2

            scored_products.append((score, product))

        # --------------------------------------------------
        # 8. Remove products with no query relevance
        # --------------------------------------------------

        if keywords or features or requested_category:
            scored_products = [
                (score, product)
                for score, product in scored_products
                if relevance_by_id.get(product.id, 0) > 0
            ]

        # --------------------------------------------------
        # 9. Sort results
        # --------------------------------------------------

        if requirements.sort_by == "price_ascending":

            scored_products.sort(
                key=lambda item: (
                    item[1].price,
                    -(float(item[1].rating or 0)),
                )
            )

        elif requirements.sort_by == "price_descending":

            scored_products.sort(
                key=lambda item: (
                    -item[1].price,
                    -(float(item[1].rating or 0)),
                )
            )

        elif requirements.sort_by == "rating":

            scored_products.sort(
                key=lambda item: (
                    -(float(item[1].rating or 0)),
                    -item[0],
                )
            )

        else:

            scored_products.sort(
                key=lambda item: (
                    -item[0],
                    -float(item[1].rating or 0),
                )
            )

        # --------------------------------------------------
        # 10. Return actual database records
        # --------------------------------------------------

        return [
            product_to_dict(product)
            for score, product in scored_products[:limit]
        ]

    # ------------------------------------------------------
    # Diagnostics: why did a search return nothing?
    # ------------------------------------------------------

    def diagnose(self, requirements, website_ids):
        """
        Apply the hard requirements one at a time. Returns an ordered list of
        (stage, products remaining after that stage). Used only to explain an
        empty result; it never adds products to an answer.
        """
        if isinstance(requirements, dict):
            requirements = ShoppingRequirements.model_validate(requirements)
        website_ids = [website_ids] if isinstance(website_ids, int) else list(website_ids)

        remaining = list(
            Product.objects.filter(website_id__in=website_ids, website__is_active=True)
            .select_related("website")
        )
        stages = [("in_scope", remaining)]

        def stage(name, keep):
            nonlocal remaining
            remaining = [product for product in remaining if keep(product)]
            stages.append((name, remaining))

        features = [_feature_key(f) for f in requirements.must_have_features if f and f.strip()]

        if requirements.category:
            stage("category", lambda p: category_matches(searchable_fields(p), requirements.category))
        if requirements.brand:
            stage("brand", lambda p: brand_matches(p, requirements.brand))
        if features:
            stage("features", lambda p: features_match(searchable_fields(p), features))
        if requirements.only_available:
            stage("available", lambda p: p.is_available)
        if requirements.currency:
            stage("currency", lambda p: (p.currency or "").upper() == requirements.currency.upper())
        if requirements.min_price is not None:
            stage("min_price", lambda p: p.price >= Decimal(str(requirements.min_price)))
        if requirements.max_price is not None:
            stage("max_price", lambda p: p.price <= Decimal(str(requirements.max_price)))
        if requirements.min_rating is not None:
            stage("min_rating", lambda p: p.rating is not None and p.rating >= Decimal(str(requirements.min_rating)))

        if remaining:
            found = {item["id"] for item in self.search(requirements, website_ids, limit=100)}
            stage("keywords", lambda p: p.id in found)

        return stages
