"""
Deterministic checks that run BEFORE any model call.

- Requests for code, essays, stories, translations and similar non-shopping
  work are redirected (out_of_scope) unless the message also clearly talks
  about shopping.
- Plain greetings get a short introduction.
"""
import re

OUT_OF_SCOPE_REPLY = (
    "I'm EcommerceAI, a shopping assistant, so I can only help you find, compare "
    "and understand products from the selected websites. For example, try "
    "\"Suggest wireless headphones under $200\" or "
    "\"Which of these laptops has the best rating?\""
)

GREETING_REPLY = (
    "Hello! I'm EcommerceAI, your shopping assistant. Tell me what you're looking "
    "for - for example \"noise-cancelling headphones under $300\" - and I'll search "
    "the selected websites."
)

_NON_SHOPPING = re.compile(
    r"\b(?:write (?:a|an|me|some)|python|javascript|java|typescript|c\+\+|html|css|sql|"
    r"code|coding|program|programs|script|scripts|function|algorithm|build me|"
    r"make me a (?:website|app)|website|webpage|app for|essay|story|stories|poem|poems|"
    r"lyrics|homework|assignment|translate|translation)\b",
    re.IGNORECASE,
)

_SHOPPING = re.compile(
    r"\b(?:buy|buying|purchase|price|prices|priced|cost|product|products|item|items|"
    r"compare|comparison|budget|cheap|cheaper|cheapest|expensive|rating|rated|review|reviews|"
    r"store|shop|shopping|deal|deals|discount|sale|order|delivery|shipping|warranty|brand|"
    r"recommend|suggest|headphones?|earbuds?|laptops?|notebooks?|phones?|smartphones?|"
    r"tablets?|shoes|sneakers|watch|watches|smartwatch(?:es)?|camera|cameras|tv|television|"
    r"speaker|speakers|keyboard|mouse|monitor|charger|power bank|console)\b",
    re.IGNORECASE,
)

_GREETING = re.compile(
    r"^(?:hi|hello|hey|hiya|namaste|good (?:morning|afternoon|evening))"
    r"(?:[ ,]+(?:there|team|ecommerceai))?"
    r"(?:[ ,]+(?:what can you (?:help me with|do)|who are you))?$",
    re.IGNORECASE,
)


def is_out_of_scope(message):
    return bool(_NON_SHOPPING.search(message)) and not _SHOPPING.search(message)


def is_greeting(message):
    # Quotation marks around the message ("Hello") must not hide a greeting.
    cleaned = re.sub(r"[\"'\u201c\u201d\u2018\u2019`]+", "", message)
    normalized = re.sub(r"\s+", " ", cleaned).strip(" .!?,").lower()
    return bool(_GREETING.fullmatch(normalized)) or normalized in (
        "what can you do", "what can you help me with", "who are you",
    )


def check(message):
    """Return 'out_of_scope', 'greeting' or None (continue normally)."""
    if is_greeting(message):
        return "greeting"
    if is_out_of_scope(message):
        return "out_of_scope"
    return None
