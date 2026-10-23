"""
Currency policy. Prices are never converted and never compared across currencies.

1. If the user stated a currency, filter to it.
2. Otherwise look at the products that match every other hard requirement in
   the selected websites. If they all share one currency, use it.
3. If they use several currencies, ask which currency to use (listing the codes).
"""
import re
from dataclasses import dataclass, field

from assistant.services.product_search_service import ProductSearchService

SYMBOLS = {"$": "USD", "₹": "INR", "€": "EUR", "£": "GBP"}
NAMES = {
    "USD": r"usd|us dollars?|dollars?",
    "INR": r"inr|indian rupees?|rupees?|rs\.?",
    "EUR": r"eur|euros?",
    "GBP": r"gbp|british pounds?|pounds?",
}


@dataclass
class CurrencyDecision:
    currency: str | None
    clarification: str | None = None
    options: list[str] = field(default_factory=list)


def _join(codes):
    return codes[0] if len(codes) == 1 else ", ".join(codes[:-1]) + " and " + codes[-1]


def decide_currency(requirements, website_ids, search_service=None):
    if requirements.currency:
        return CurrencyDecision(requirements.currency.upper(), options=[requirements.currency.upper()])

    search_service = search_service or ProductSearchService()
    candidates = search_service.search(requirements, website_ids, limit=100)
    codes = sorted({(p["currency"] or "").upper() for p in candidates if p.get("currency")})

    if len(codes) <= 1:
        return CurrencyDecision(codes[0] if codes else None, options=codes)

    return CurrencyDecision(
        None,
        clarification=(
            f"The matching products in your selected websites are priced in {_join(codes)}. "
            f"Which currency should I use? I never convert or compare prices across currencies."
        ),
        options=codes,
    )


def currency_from_reply(message, options):
    """Return the chosen currency code if the reply names one of the offered options."""
    text = message.strip().lower()
    for symbol, code in SYMBOLS.items():
        if symbol in message and code in options:
            return code
    for code in options:
        pattern = NAMES.get(code, re.escape(code.lower()))
        if re.search(rf"(?<![a-z])(?:{pattern}|{re.escape(code.lower())})(?![a-z])", text):
            return code
    return None
