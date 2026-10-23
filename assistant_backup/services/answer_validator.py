"""
Checks a generated answer against the product records it was based on.

Every price written next to a currency (symbol or ISO code), every rating and
every URL in the answer must come from the supplied products. If anything else
appears, the answer is discarded and render_template_answer() builds a
deterministic answer from the records instead.
"""
import re
from decimal import Decimal, InvalidOperation

SYMBOLS = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP"}
KNOWN_CODES = {"USD", "INR", "EUR", "GBP", "AUD", "CAD", "JPY", "AED", "SGD", "CHF", "CNY"}

_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_MONEY = re.compile(
    rf"(?P<sym>[$₹€£])\s?(?P<a>{_NUMBER})"
    rf"|(?:\bRs\.?\s?)(?P<rs>{_NUMBER})"
    rf"|(?P<b>{_NUMBER})\s?(?P<code>[A-Z]{{3}})\b"
    rf"|\b(?P<code2>[A-Z]{{3}})\s?(?P<c>{_NUMBER})"
)
_RATING = re.compile(
    rf"rating\**\s*[:\-]?\s*\**\s*(?P<a>\d(?:\.\d+)?)"
    rf"|(?P<b>\d(?:\.\d+)?)\s*(?:/\s*5\b|out of 5|stars?\b)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s<>\"')\]]+")


def _money(text):
    try:
        return Decimal(text.replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _rating(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _clean_url(url):
    return url.rstrip(".,;:!?*").rstrip("/")


def allowed_values(products):
    prices, ratings, urls, codes = set(), set(), set(), set(KNOWN_CODES)
    for p in products:
        for key in ("price", "original_price"):
            if p.get(key) not in (None, ""):
                value = _money(str(p[key]))
                if value is not None:
                    prices.add(value)
        if p.get("rating") is not None:
            ratings.add(_rating(p["rating"]))
        for key in ("product_url", "image_url"):
            if p.get(key):
                urls.add(_clean_url(p[key]))
        if p.get("currency"):
            codes.add(p["currency"].upper())
    return prices, ratings, urls, codes


def find_violations(answer, products, user_prices=(), user_ratings=()):
    """
    Return a list of unsupported values found in the answer (empty = valid).
    The user's own budget and minimum rating may be repeated in the answer.
    """
    prices, ratings, urls, codes = allowed_values(products)
    prices |= {_money(str(v)) for v in user_prices if v is not None}
    ratings |= {_rating(v) for v in user_ratings if v is not None}
    problems = []

    for match in _MONEY.finditer(answer):
        if match.group("code") and match.group("code") not in codes:
            continue
        if match.group("code2") and match.group("code2") not in codes:
            continue
        number = match.group("a") or match.group("rs") or match.group("b") or match.group("c")
        value = _money(number)
        if value is not None and value not in prices:
            problems.append(f"price {match.group(0).strip()}")

    for match in _RATING.finditer(answer):
        value = _rating(match.group("a") or match.group("b"))
        if value is not None and value not in ratings:
            problems.append(f"rating {value}")

    for match in _URL.finditer(answer):
        if _clean_url(match.group(0)) not in urls:
            problems.append("url")

    return problems


def _fmt_price(product):
    return f"{product.get('price')} {product.get('currency') or ''}".strip()


def render_template_answer(products, limit=8):
    """Deterministic answer built only from the product records."""
    if not products:
        return "I couldn't find matching products in the selected websites."
    lines = [f"I found {len(products)} matching product{'s' if len(products) != 1 else ''}:"]
    for p in products[:limit]:
        lines.append("")
        lines.append(f"**{p.get('title')}**")
        if p.get("brand"):
            lines.append(f"- Brand: {p['brand']}")
        lines.append(f"- Price: {_fmt_price(p)}")
        if p.get("rating") is not None:
            lines.append(f"- Rating: {p['rating']}")
        lines.append(f"- Availability: {'In stock' if p.get('is_available') else 'Out of stock'}")
        lines.append(f"- Website: {p.get('website_name')}")
        if p.get("product_url"):
            lines.append(f"- Link: {p['product_url']}")
    if len(products) > limit:
        lines.append("")
        lines.append(f"{len(products) - limit} more are shown in the product list.")
    return "\n".join(lines)


def validate_answer(answer, products, requirements=None):
    """Return (answer_to_use, was_valid)."""
    user_prices = (requirements.min_price, requirements.max_price) if requirements else ()
    user_ratings = (requirements.min_rating,) if requirements else ()
    if find_violations(answer, products, user_prices, user_ratings):
        return render_template_answer(products), False
    return answer, True
