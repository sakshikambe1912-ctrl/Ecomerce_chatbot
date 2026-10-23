"""
Decides whether a message continues the previous request or starts a new one.

Without this, every constraint of an earlier question (brand, features, category)
leaks into later, unrelated questions when the user does not start a new
conversation. The rules are deterministic, so a small language model cannot
get them wrong.
"""
import re

# The user points at earlier results or edits earlier filters: always a follow-up.
_STRONG = re.compile(
    r"\b(?:it|its|they|them|their|those|these|that one|this one|the same|same ones?|"
    r"previous|above|the (?:first|second|third|last) one|all of them|"
    r"remove|without|ignore|drop|clear|reset|no budget|no price limit|"
    r"any price|any brands?|all brands|any rating|show all)\b",
    re.IGNORECASE,
)

# Wording that usually modifies an earlier request (only counts without a new product type).
_WEAK = re.compile(
    r"\b(?:instead|also|actually|another|other|others|else|cheaper|pricier|"
    r"more expensive|less expensive|increase|decrease|raise|lower|reduce|only|just|"
    r"what about|how about|which (?:one|ones|of|has|is|have)|best rating|"
    r"highest rated|top rated|more|less|bigger|smaller)\b",
    re.IGNORECASE,
)

# The user is asking about the whole catalog ("products under $50", "cheapest item").
_GENERIC = re.compile(
    r"\b(?:products?|items?|things?|stuff|everything|anything|catalog|store)\b",
    re.IGNORECASE,
)

_FILLER = {
    "show", "me", "find", "get", "give", "search", "looking", "look", "for", "want",
    "need", "buy", "suggest", "recommend", "please", "some", "any", "the", "and",
    "with", "under", "over", "below", "above", "than", "that", "this", "you", "have",
    "sell", "there", "are", "can", "do", "does", "best", "cheap", "cheapest",
}


def _singular(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def topic_tokens(requirements):
    """Words naming the product type (category and keywords), without brand or filler."""
    data = requirements if isinstance(requirements, dict) else requirements.model_dump()
    brand_words = set(re.findall(r"[a-z0-9]+", (data.get("brand") or "").lower()))
    text = " ".join([data.get("category") or "", *(data.get("keywords") or [])]).lower()
    tokens = set()
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) <= 2 or word in _FILLER or word in brand_words:
            continue
        if _GENERIC.fullmatch(word) or word in ("product", "item"):
            continue
        tokens.add(_singular(word))
    return tokens


def might_follow_up(message):
    """Before extraction: should the model see the earlier conversation at all?"""
    if _STRONG.search(message) or _WEAK.search(message):
        return True
    return len(message.split()) <= 4 and not _GENERIC.search(message)


def is_follow_up(message, requirements, previous):
    """After extraction: merge with the previous request (True) or start fresh (False)."""
    if not previous:
        return False
    if _STRONG.search(message):
        return True
    if _GENERIC.search(message):
        return False

    topic = topic_tokens(requirements)
    if topic:
        # Same product type as before is a refinement; a different one is a new request.
        return bool(topic & topic_tokens(previous))

    data = requirements.model_dump()
    has_constraint = any([
        data.get("max_price") is not None,
        data.get("min_price") is not None,
        data.get("min_rating") is not None,
        data.get("brand"),
        data.get("must_have_features"),
        data.get("sort_by") not in (None, "relevance"),
    ])
    return bool(_WEAK.search(message)) or has_constraint


def is_listing_request(message):
    """'Products under $50', 'cheapest item': the whole catalog, not a described need."""
    return bool(_GENERIC.search(message))
