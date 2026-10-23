"""
Questions about a product the user names ("the Kindle", "PlayStation 5 price").

A small model sometimes files such questions as general advice or asks for
clarification. Finding the named product in the catalog, in code, keeps the
answer tied to stored data.
"""
import re

from products.models import Product
from assistant.services.product_search_service import product_to_dict

# Title words that are ordinary English, not names.
_COMMON_FIRST_WORDS = {
    "classic", "ceramic", "smart", "wireless", "portable", "electric", "digital",
    "mechanical", "cordless", "premium", "original", "new", "pro", "ultra", "max",
    "mini", "men", "women", "mens", "womens",
}


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _contains(text, phrase):
    return bool(phrase) and f" {phrase} " in f" {text} "


def _keys(product):
    """(multi-word keys, single-word keys) a user might use to name this product."""
    words = _norm(product.title).split()
    brand = _norm(product.brand)
    brand_words = set(brand.split())
    # The title without its brand and without a year, e.g. 'macbook air 13 inch ...'.
    core = [w for w in words if w not in brand_words and not re.fullmatch(r"20\d\d", w)]

    multi = set()
    for source in (words, core):
        for n in (2, 3, 4):
            if len(source) >= n:
                multi.add(" ".join(source[:n]))
    if len(brand.split()) >= 2:
        multi.add(brand)

    single = set()
    if brand and len(brand.split()) == 1 and len(brand) >= 3:
        single.add(brand)
    first = core[0] if core else ""
    if len(first) >= 5 and first not in _COMMON_FIRST_WORDS:
        single.add(first)
    return multi, single


def find_named_products(message, website_ids):
    """
    Returns (exact, loose). `exact` are products named by a multi-word name
    ("playstation 5"); `loose` are products named only by brand or first word
    ("the Kindle", "Sony headphones"). `loose` is empty when `exact` is not.
    """
    text = _norm(message)
    products = Product.objects.filter(
        website_id__in=website_ids, website__is_active=True
    ).select_related("website")

    exact, loose = [], []
    for product in products:
        multi, single = _keys(product)
        if any(_contains(text, key) for key in multi):
            exact.append(product)
        elif any(_contains(text, key) for key in single):
            loose.append(product)
    return [product_to_dict(p) for p in exact], ([] if exact else [product_to_dict(p) for p in loose])


_PRICE = re.compile(r"\b(?:price|prices|priced|cost|costs|how much)\b", re.IGNORECASE)
_STOCK = re.compile(r"\b(?:in stock|stock|available|availability|out of stock)\b", re.IGNORECASE)
_RATING = re.compile(r"\b(?:rating|rated|stars?|reviews?)\b", re.IGNORECASE)


def facts_answer(message, product):
    """
    A fully grounded answer for plain price / stock / rating questions about one
    product. Returns None for anything else (the language model handles those).
    """
    title, currency = product["title"], product["currency"]
    parts = []
    if _PRICE.search(message):
        line = f"{title} costs {product['price']} {currency}"
        original = product.get("original_price")
        if original and float(original) > float(product["price"]):
            line += f" (list price {original} {currency})"
        parts.append(line + ".")
    if _STOCK.search(message):
        state = "in stock" if product.get("is_available") else "out of stock"
        parts.append(f"{title} is currently {state}.")
    if _RATING.search(message) and product.get("rating") is not None:
        line = f"{title} has a rating of {product['rating']}"
        if product.get("review_count"):
            line += f" from {product['review_count']:,} reviews"
        parts.append(line + ".")
    return " ".join(parts) or None
