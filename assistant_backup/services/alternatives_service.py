"""
Near misses, shown separately from the matches.

An alternative fails EXACTLY ONE of these requirements:
- min_rating (rated lower, or not rated),
- max_price, by at most 15 percent,
- one must-have feature.
Website scope, currency, availability, brand and category are never relaxed.
Alternatives are returned in their own 'alternatives' list with an 'unmet'
list and are never presented as matches.
"""
from decimal import Decimal

from assistant.services.product_search_service import ProductSearchService

MAX_ALTERNATIVES = 3
PRICE_TOLERANCE = Decimal("0.15")
INTRO = "These do not fully match your request:"


def _fmt(amount):
    return f"{Decimal(str(amount)):.2f}"


def find_alternatives(requirements, website_ids, exclude_ids=(), limit=MAX_ALTERNATIVES):
    search = ProductSearchService()
    excluded = set(exclude_ids)
    found = []

    def collect(relaxed, unmet_for):
        for product in search.search(relaxed, website_ids, limit=100):
            if product["id"] in excluded:
                continue
            unmet = unmet_for(product)
            if unmet:
                excluded.add(product["id"])
                found.append({**product, "unmet": [unmet]})

    if requirements.max_price is not None:
        ceiling = Decimal(str(requirements.max_price)) * (1 + PRICE_TOLERANCE)
        relaxed = requirements.model_copy(update={"max_price": float(ceiling), "sort_by": "price_ascending"})
        currency = requirements.currency or ""

        def over_budget(product):
            price = Decimal(str(product["price"]))
            if Decimal(str(requirements.max_price)) < price <= ceiling:
                return (f"Price {product['price']} {product['currency']} is above your budget of "
                        f"{_fmt(requirements.max_price)} {currency}".rstrip())
            return None

        collect(relaxed, over_budget)

    if requirements.min_rating is not None:
        relaxed = requirements.model_copy(update={"min_rating": None, "sort_by": "rating"})

        def low_rating(product):
            rating = product.get("rating")
            if rating is None:
                return f"Not rated (you asked for {requirements.min_rating:g} or higher)"
            if float(rating) < requirements.min_rating:
                return f"Rated {float(rating):g}, below your minimum of {requirements.min_rating:g}"
            return None

        collect(relaxed, low_rating)

    for feature in requirements.must_have_features:
        others = [f for f in requirements.must_have_features if f != feature]
        relaxed = requirements.model_copy(update={"must_have_features": others})
        strict_ids = {p["id"] for p in search.search(requirements, website_ids, limit=100)}
        collect(relaxed, lambda product, feature=feature:
                None if product["id"] in strict_ids else f"Does not list {feature}")

    return found[:limit]


def render_alternatives(alternatives):
    """Deterministic text for the alternatives section (values come from the records)."""
    if not alternatives:
        return ""
    lines = [INTRO]
    for product in alternatives:
        lines.append(f"- **{product['title']}** ({product['price']} {product['currency']}, "
                     f"{product['website_name']}): {'; '.join(product['unmet'])}")
    return "\n".join(lines)
