"""
Explains, without any model call, why a search returned nothing.

ProductSearchService.diagnose() applies the hard requirements one at a time
and records how many products remain after each stage. The no-match message
names the first stage that removes every remaining product, says how many
passed the stages before it, and suggests the single easiest change.

Stages (only those the request uses): in_scope, category, brand, features,
available, currency, min_price, max_price, min_rating, keywords.
"""
from collections import Counter
from decimal import Decimal


def _fmt(amount):
    return f"{Decimal(str(amount)):.2f}"


def _count(n, singular, plural=None):
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _join(items):
    items = [str(item) for item in items]
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _currency(requirements, products):
    if requirements.currency:
        return requirements.currency
    codes = {p.currency for p in products}
    return codes.pop() if len(codes) == 1 else ""


def _passed_phrase(stage, n, requirements):
    verb = "is" if n == 1 else "are"
    cur = f" {requirements.currency}" if requirements.currency else ""
    if stage == "category":
        return f"{n} {'matches' if n == 1 else 'match'} \"{requirements.category}\""
    if stage == "brand":
        return f"{n} {verb} from {requirements.brand}"
    if stage == "features":
        return f"{n} {'lists' if n == 1 else 'list'} {_join(requirements.must_have_features)}"
    if stage == "available":
        return f"{n} {verb} in stock"
    if stage == "currency":
        return f"{n} {verb} priced in {requirements.currency}"
    if stage == "min_price":
        return f"{n} {'costs' if n == 1 else 'cost'} at least {_fmt(requirements.min_price)}{cur}"
    if stage == "max_price":
        return f"{n} {'costs' if n == 1 else 'cost'} at most {_fmt(requirements.max_price)}{cur}"
    if stage == "min_rating":
        return f"{n} {verb} rated {requirements.min_rating} or higher"
    return f"{n} {verb} left"


def _blocking_sentence(stage, requirements, before):
    """'none is ...' plus one fact about the products that were still left, and a suggestion."""
    cur = _currency(requirements, before)
    if stage == "category":
        top = [c for c, _ in Counter(p.category for p in before if p.category).most_common(4)]
        tail = f" Product types available include {_join(top)}." if top else ""
        return f"none matches \"{requirements.category}\".{tail}", "Try a different product type."
    if stage == "brand":
        brands = sorted({p.brand for p in before if p.brand})[:5]
        tail = f" Brands available: {_join(brands)}." if brands else ""
        return f"none is from {requirements.brand}.{tail}", "Remove the brand filter or choose another brand."
    if stage == "features":
        return (f"none lists {_join(requirements.must_have_features)}.",
                "Remove one of the required features.")
    if stage == "available":
        return "none is currently in stock.", "Ask to include out-of-stock products."
    if stage == "currency":
        codes = sorted({p.currency for p in before})
        return (f"none is priced in {requirements.currency}. Prices are listed in {_join(codes)}.",
                f"Choose {_join(codes)} instead.")
    if stage == "min_price":
        highest = max(p.price for p in before)
        return (f"none costs {_fmt(requirements.min_price)} {cur} or more. The highest price is {_fmt(highest)} {cur}.",
                f"Lower your minimum price to {_fmt(highest)} {cur} or less.")
    if stage == "max_price":
        lowest = min(p.price for p in before)
        what = f" for {requirements.category}" if requirements.category else ""
        return (f"none costs {_fmt(requirements.max_price)} {cur} or less. The lowest price{what} is {_fmt(lowest)} {cur}.",
                f"Raise your budget to at least {_fmt(lowest)} {cur}.")
    if stage == "min_rating":
        best = max((p.rating for p in before if p.rating is not None), default=None)
        best = f"{float(best):g}" if best is not None else None
        fact = f" The highest rating is {best}." if best is not None else " None of them has a rating."
        suggestion = f"Lower the minimum rating to {best}." if best is not None else "Remove the rating requirement."
        return f"none is rated {requirements.min_rating} or higher.{fact}", suggestion
    if stage == "keywords":
        return "none matches the words in your request.", "Describe the product differently."
    return "none matches.", "Relax one of your requirements."


def build_no_match_message(requirements, stages):
    """
    `stages` is the ordered list of (stage, products_remaining_after_stage)
    from ProductSearchService.diagnose(). Returns a deterministic message.
    """
    if not stages:
        return "I couldn't find matching products in the selected websites."

    in_scope = stages[0][1]
    if not in_scope:
        return ("The selected websites have no products yet, so there is nothing to search. "
                "Try selecting another website.")

    parts = [f"{_count(len(in_scope), 'product')} {'is' if len(in_scope) == 1 else 'are'} in your selected websites"]
    before = in_scope
    for stage, remaining in stages[1:]:
        if not remaining:
            sentence, suggestion = _blocking_sentence(stage, requirements, before)
            return "; ".join(parts) + f"; {sentence} {suggestion}"
        parts.append(_passed_phrase(stage, len(remaining), requirements))
        before = remaining

    return "I couldn't find products matching all your requirements. Try relaxing one of them."
