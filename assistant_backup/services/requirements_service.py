import json
import re
from typing import Literal

import logging

from pydantic import BaseModel, Field, ValidationError, model_validator

from assistant.services.llm_service import LLMService, call_llm

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured shopping requirements for EcommerceAI. Use "
    "conversation context when available. Return valid JSON only."
)
STRICT_RETRY_INSTRUCTION = (
    "Your previous reply was not valid. Return ONLY one JSON object with exactly "
    "the fields listed above. No Markdown, no explanation."
)


# ==========================================================
# 1. SHOPPING REQUIREMENTS MODEL
# ==========================================================

class ShoppingRequirements(BaseModel):

    intent: Literal[
        "product_search",
        "product_comparison",
        "general_question",
        "out_of_scope",
        "clarification_needed",
    ] = "product_search"

    keywords: list[str] = Field(default_factory=list)

    category: str | None = None

    brand: str | None = None

    min_price: float | None = None

    max_price: float | None = None

    currency: str | None = None

    min_rating: float | None = None

    only_available: bool = True

    must_have_features: list[str] = Field(
        default_factory=list
    )

    sort_by: Literal[
        "relevance",
        "price_ascending",
        "price_descending",
        "rating",
    ] = "relevance"

    @model_validator(mode="after")
    def validate_requirements(self):

        # Validate minimum price.
        if self.min_price is not None and self.min_price < 0:
            raise ValueError(
                "Minimum price cannot be negative."
            )

        # Validate maximum price.
        if self.max_price is not None and self.max_price < 0:
            raise ValueError(
                "Maximum price cannot be negative."
            )

        # Minimum price must not exceed maximum price.
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError(
                "Minimum price cannot exceed maximum price."
            )

        # Validate rating.
        if self.min_rating is not None:
            if not 0 <= self.min_rating <= 5:
                raise ValueError(
                    "Rating must be between 0 and 5."
                )

        # Validate currency.
        if self.currency is not None:
            self.currency = self.currency.strip().upper()

            if not re.fullmatch(r"[A-Z]{3}", self.currency):
                raise ValueError(
                    "Currency must be a three-letter currency code."
                )

        return self


# ==========================================================
# 2. REQUIREMENTS SERVICE
# ==========================================================

class RequirementsService:

    def __init__(self):
        self.llm_service = LLMService()

    # ------------------------------------------------------
    # 3. EXTRACT REQUIREMENTS USING THE CONFIGURED LLM
    # ------------------------------------------------------

    def extract(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
    ) -> ShoppingRequirements:
        """
        Extract shopping requirements from the user's message.

        Uses recent conversation history to understand follow-up
        questions and previously stated shopping preferences.
        """

        if not user_message or not user_message.strip():
            raise ValueError(
                "User message cannot be empty."
            )

        user_message = user_message.strip()

        # Prepare recent conversation history.
        history_text = ""

        if conversation_history:
            history_lines = []

            for item in conversation_history[-10:]:
                role = item.get("role", "user")
                content = item.get("content", "")

                if role in ("user", "assistant") and content:
                    history_lines.append(
                        f"{role.capitalize()}: {content}"
                    )

            history_text = "\n".join(history_lines)

        # Structured requirement extraction prompt.
        prompt = f"""
You are the requirement extraction engine for EcommerceAI.

Your task is to extract the user's CURRENT shopping requirements.

Use previous conversation messages to understand follow-up requests.

Return one valid JSON object containing exactly these fields:

{{
    "intent": "product_search",
    "keywords": [],
    "category": null,
    "brand": null,
    "min_price": null,
    "max_price": null,
    "currency": null,
    "min_rating": null,
    "only_available": true,
    "must_have_features": [],
    "sort_by": "relevance"
}}

RULES:

1. Use product_search for requests to find, filter, or display products.

2. Use product_comparison when comparing products.

3. Use general_question for shopping or buying knowledge questions that
   are not a search of the catalog (for example "is noise cancellation
   worth it for flights?" or "what should I look for in a laptop?").

3a. Use out_of_scope for anything unrelated to shopping (code, essays,
    homework, translations, general chit-chat).

4. Use clarification_needed when the request cannot reasonably
   be interpreted without clarification.

5. Requests such as "show all brands", "show all options",
   "remove the brand filter", and "remove my budget limit" are
   product_search requests when they refer to an existing shopping
   conversation.

6. For a filter-removal request, preserve the previous product category
   and other applicable requirements while removing only the requested
   filter.

7. Never invent a brand, budget, rating, or feature.

8. Extract the product type into keywords and category when appropriate.

9. Category should represent the general product type, not necessarily
   the exact category label used by a retailer.

10. Interpret "under 5000" as max_price = 5000.

11. Interpret "above 4 stars" as min_rating = 4.0.

12. Interpret "at least 4 stars" as min_rating = 4.0.

13. Interpret "highly rated", "best rated", and "top rated" as a
    qualitative rating preference. Use min_rating = 4.0 for these
    phrases unless the user specifies another threshold.

14. Use rating when the user explicitly requests highest-rated products
    or uses a qualitative rating preference.

15. Use price_ascending for "cheapest first".

16. Use price_descending for "most expensive first".

17. Otherwise, use relevance.

18. Preserve requested features such as wireless connectivity,
    battery life, durability, compatibility, and noise cancellation
    in must_have_features.

19. For explicitly specified currencies, use ISO 4217 currency codes:
    USD for US dollars, INR for Indian rupees, GBP for British pounds,
    and EUR for euros.

20. A clear "$" amount normally indicates USD unless the user's
    context clearly specifies another dollar currency.

21. Use INR for an explicit rupee symbol or an unambiguous Indian
    rupee amount.

22. If the currency is genuinely ambiguous, use null.

23. Do not assume that an unspecified currency matches the currency
    of the product catalog.

24. Do not invent product facts.

25. Return JSON only. Do not include Markdown or explanations.

26. Use previous conversation messages to understand follow-up questions.

27. Preserve earlier product category, budget, currency, brand, and
    feature requirements when the user has not changed them.

28. If the user explicitly changes a requirement, use the new value.

29. Interpret follow-ups such as "Which has the best rating?"
    using the previous conversation.

30. Previous assistant recommendations are not verified product records.
    Product facts must come from product search results.

31. Return the current effective requirements, not a conversation summary.

32. If the user explicitly removes a constraint, set that field to null
    or an empty list as appropriate.

33. If the user says "remove my budget", "no budget limit", or
    "show products at any price", set min_price and max_price to null.

34. If the user says "remove the brand filter" or "show all brands",
    set brand to null.

35. If the user replaces one brand with another, return the new brand.

36. If the user changes their budget, return the new budget.

37. If the user removes a required feature, remove that feature from
    must_have_features.

38. Do not carry over shopping requirements from unrelated topics.

39. For a follow-up about the same shopping request, preserve relevant
    previous constraints unless the user changes them.

40. Return the effective requirements using the previous conversation
    as context, but never invent product facts.

PREVIOUS CONVERSATION:

{history_text if history_text else "No previous conversation."}

CURRENT USER MESSAGE:

{json.dumps(user_message)}
"""

        # Ask the model; if the reply is not valid JSON for our schema, retry
        # once with a stricter instruction, then fall back to deterministic
        # extraction. Provider outages raise ModelUnavailableError (HTTP 503).
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        requirements = self._ask_model(messages)
        if requirements is None:
            requirements = self._ask_model(
                messages + [{"role": "user", "content": STRICT_RETRY_INSTRUCTION}]
            )
        if requirements is None:
            logger.warning("Requirement extraction returned invalid JSON twice; using heuristics.")
            return self.heuristic_requirements(user_message)

        # Apply deterministic rules for common shopping preferences.
        requirements = self._apply_preference_rules(
            requirements,
            user_message,
        )

        return requirements

    def _ask_model(self, messages):
        """One extraction call. Returns ShoppingRequirements, or None if the reply is unusable."""
        content = call_llm(
            self.llm_service,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        if not content or not content.strip():
            return None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        try:
            return ShoppingRequirements.model_validate(data)
        except ValidationError:
            return None

    # ------------------------------------------------------
    # 3b. DETERMINISTIC FALLBACK EXTRACTION
    # ------------------------------------------------------

    def heuristic_requirements(self, user_message):
        """
        Extract requirements without the model: price limits ('under N'),
        ratings ('above 4 stars'), known brands, category words, 'cheapest',
        'best rated'. If nothing usable is found, ask the user to clarify.
        """
        base = ShoppingRequirements()
        message = user_message.lower()
        budget = re.search(
            r"\bbudget\s+(?:to|of|is|at)\s+[$₹€£]?\s*(\d[\d,]*(?:\.\d+)?)", message
        )
        if budget:
            base = base.model_copy(update={"max_price": float(budget.group(1).replace(",", ""))})

        result = self._apply_preference_rules(base, user_message)
        found = any([
            result.category,
            result.brand,
            result.min_price is not None,
            result.max_price is not None,
            result.min_rating is not None,
            result.must_have_features,
            result.sort_by != "relevance",
        ])
        if result.intent == "general_question":
            return result
        if not found:
            return ShoppingRequirements(intent="clarification_needed")
        return result.model_copy(update={"intent": "product_search"})

    # ------------------------------------------------------
    # 4. APPLY DETERMINISTIC PREFERENCE RULES
    # ------------------------------------------------------

    def _apply_preference_rules(
        self,
        requirements: ShoppingRequirements,
        user_message: str,
    ) -> ShoppingRequirements:
        """
        Apply deterministic rules for common shopping preferences.

        The language model handles flexible interpretation.
        These rules make frequently used phrases more consistent.
        """

        message = user_message.lower()
        data = requirements.model_dump()

        # Detect explicit rating preferences in the current message.
        has_numeric_rating = bool(re.search(
            r"\b(?:at least|minimum|min\.?|above|over|"
            r"rated|rating of)\s*\d(?:\.\d)?\s*"
            r"(?:stars?|/5)\b",
            message,
        ))

        has_qualitative_rating = bool(re.search(
            r"\b(?:highly rated|best[- ]rated|highest rated|"
            r"top[- ]rated|good rating|best rating)\b",
            message,
        ))

        # Do not accept an unsupported rating inferred by the LLM.
        if not has_numeric_rating and not has_qualitative_rating:
            data["min_rating"] = None

        # --------------------------------------------------
        # 1. Rating preferences
        # --------------------------------------------------

        numeric_rating = re.search(
            r"\b(?:at least|minimum|min\.?|above|over|"
            r"rated|rating of)\s*(\d(?:\.\d)?)\s*"
            r"(?:stars?|/5)?\b",
            message,
        )

        qualitative_rating = re.search(
            r"\b(?:highly rated|best[- ]rated|highest rated|"
            r"top[- ]rated|good rating|best rating)\b",
            message,
        )

        if numeric_rating:
            rating = float(numeric_rating.group(1))

            # "Above 4 stars" means strictly greater than 4.
            if re.search(r"\b(?:above|over)\b", message):
                rating = round(rating + 0.1, 1)

            data["min_rating"] = min(rating, 5.0)
            data["sort_by"] = "rating"

        elif qualitative_rating:
            if data.get("min_rating") is None:
                data["min_rating"] = 4.0

            data["sort_by"] = "rating"

        # --------------------------------------------------
        # 2. Explicit sorting preferences
        # --------------------------------------------------

        if re.search(
            r"\b(?:cheapest|lowest price|price low to high)\b",
            message,
        ):
            data["sort_by"] = "price_ascending"

        elif re.search(
            r"\b(?:most expensive|highest price|price high to low)\b",
            message,
        ):
            data["sort_by"] = "price_descending"

        elif re.search(
            r"\b(?:highest rated|best[- ]rated|top[- ]rated|"
            r"sort by rating|highest rating first)\b",
            message,
        ):
            data["sort_by"] = "rating"

        # --------------------------------------------------
        # 3. Explicit product features
        # --------------------------------------------------

        feature_patterns = {
            "wireless": r"\bwireless\b",
            "bluetooth": r"\bbluetooth\b",
            "noise cancellation": (
            r"\bnoise[- ]cancell?ation\b"
            r"|\bnoise[- ]cancell?ing\b"
            r"|\bactive noise cancellation\b"
            r"|\bANC\b"
            ),
            "waterproof": r"\bwaterproof\b",
            "water resistant": r"\bwater[- ]resistant\b",
            "long battery life": (
                r"\b(?:long|longer|extended)"
                r"\s+battery life\b"
            ),
            "fast charging": r"\bfast charging\b",
            "portable": r"\bportable\b",

            "high battery capacity": (
    r"\b(?:high|large|higher|greater)"

    r"\s+battery capacity\b"
       ),
"high capacity": (
    r"\b(?:high|large|higher)"
    r"\s+capacity\b"
),
"lightweight": r"\blight[- ]?weight\b",
"multi-device connectivity": (
    r"\bconnect(?:s|ed|ing)?\s+to\s+"
    r"(?:multiple|several|two|three)\s+devices\b"
    r"|\bmultiple device connectivity\b"
),
        }

        detected_features = [
            feature
            for feature, pattern in feature_patterns.items()
            if re.search(pattern, message)
        ]

        # --------------------------------------------------
        # 3. Normalize mandatory features
        # --------------------------------------------------

        # Remove terms that represent structured constraints.
        invalid_features = {
            "price",
            "rating",
            "budget",
            "category",
            "brand",
            "availability",
            "relevance",
        }

        # These terms represent product types, not mandatory features.
        product_type_features = {
            "headphone",
            "headphones",
            "wireless headphone",
            "wireless headphones",
            "headset",
            "headsets",
            "laptop",
            "laptops",
            "notebook",
            "notebooks",
            "smartphone",
            "smartphones",
            "mobile phone",
            "mobile phones",
            "tablet",
            "tablets",
            "keyboard",
            "keyboards",
            "mouse",
            "mice",
            "monitor",
            "monitors",
            "speaker",
            "speakers",
            "earbud",
            "earbuds",
            "earphone",
            "earphones",
            "power bank",
            "power banks",
            "portable charger",
            "portable chargers",
            "charger",
            "chargers",
            "camera",
            "cameras",
            "printer",
            "printers",
            "smartwatch",
            "smartwatches",
            "television",
            "televisions",
            "tv",
            "tvs",
        }

        # Start with the original model-provided features.
        existing_features = data.get("must_have_features") or []

        # Add features detected directly in the user's message.
        for feature in detected_features:
            if feature not in existing_features:
                existing_features.append(feature)

        normalized_features = []

        for feature in existing_features:
            feature = str(feature).strip().lower()

            if not feature:
                continue

            if feature in invalid_features:
                continue

            if feature in product_type_features:
                continue

            if feature not in normalized_features:
                normalized_features.append(feature)

        data["must_have_features"] = normalized_features
        # --------------------------------------------------
        # 4. Explicit price constraints and currency
        # --------------------------------------------------

        amount_pattern = (
            r"(?P<prefix>[$₹€£])?\s*"
            r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*"
            r"(?P<suffix>dollars?|usd|rupees?|inr|"
            r"euros?|eur|pounds?|gbp)?"
        )

        upper_match = re.search(
            r"\b(?:under|below|less than|up to|at most|"
            r"maximum|max(?:imum)? price of)\s+" + amount_pattern
            + r"(?!\s*(?:stars?|/5)\b)",
            message,
        )

        lower_match = re.search(
            r"\b(?:over|above|more than|at least|"
            r"minimum price of)\s+" + amount_pattern
            + r"(?!\s*(?:stars?|/5)\b)",
            message,
        )

        def parse_amount(match):
            if not match:
                return None
            return float(match.group("amount").replace(",", ""))

        def detect_currency(match):
            if not match:
                return None

            prefix = match.group("prefix")
            suffix = (match.group("suffix") or "").lower()

            if prefix == "$" or suffix in ("dollar", "dollars", "usd"):
                return "USD"
            if prefix == "₹" or suffix in ("rupee", "rupees", "inr"):
                return "INR"
            if prefix == "€" or suffix in ("euro", "euros", "eur"):
                return "EUR"
            if prefix == "£" or suffix in ("pound", "pounds", "gbp"):
                return "GBP"
            return None

        if upper_match:
            # Explicit upper bound overrides any conflicting model output.
            data["min_price"] = None
            data["max_price"] = parse_amount(upper_match)
            detected_currency = detect_currency(upper_match)
            if detected_currency:
                data["currency"] = detected_currency

        elif lower_match:
            # Explicit lower bound overrides any conflicting model output.
            data["min_price"] = parse_amount(lower_match)
            data["max_price"] = None
            detected_currency = detect_currency(lower_match)
            if detected_currency:
                data["currency"] = detected_currency

        # Detect currency even when the amount and currency are separated.
        if re.search(r"\b(?:usd|us dollars?)\b", message):
            data["currency"] = "USD"
        elif re.search(r"\b(?:inr|indian rupees?)\b", message):
            data["currency"] = "INR"
        elif re.search(r"\b(?:eur|euros?)\b", message):
            data["currency"] = "EUR"
        elif re.search(r"\b(?:gbp|british pounds?)\b", message):
            data["currency"] = "GBP"

        # Dollar/rupee/euro/pound symbols are explicit currency signals.
        if "$" in message:
            data["currency"] = "USD"
        elif "₹" in message:
            data["currency"] = "INR"
        elif "€" in message:
            data["currency"] = "EUR"
        elif "£" in message:
            data["currency"] = "GBP"

        # --------------------------------------------------
        # 5. Normalize common product categories
        # --------------------------------------------------

        category_patterns = [
    # Audio products
    (
        r"\b(?:noise[- ]cancell?ing )?headphones?\b"
        r"|\bheadsets?\b",
        "headphones",
    ),
    (
        r"\b(?:bluetooth )?speakers?\b",
        "speaker",
    ),
    (
        r"\bearbuds?\b|\bin[- ]ear headphones?\b",
        "earbuds",
    ),

    # Computers and accessories
    (
        r"\b(?:laptops?|notebooks)\b",
        "laptop",
    ),
    (
        r"\bkeyboards?\b",
        "keyboard",
    ),
    (
        r"\b(?:computer )?mice\b|\bcomputer mouse\b",
        "mouse",
    ),
    (
        r"\bmonitors?\b|\bcomputer screens?\b",
        "monitor",
    ),
    (
        r"\bwebcams?\b",
        "webcam",
    ),

    # Mobile devices
    (
        r"\b(?:smartphones?|mobile phones?|mobiles)\b",
        "smartphone",
    ),
    (
        r"\btablets?\b|\bipad\b",
        "tablet",
    ),
    (
        r"\bsmartwatches?\b|\bwatches\b",
        "smartwatch",
    ),

    # Charging accessories
    (
        r"\b(?:power banks?|portable chargers?)\b",
        "power bank",
    ),
    (
        r"\bchargers?\b",
        "charger",
    ),

    # Other electronics
    (
        r"\b(?:televisions?|tvs?)\b",
        "television",
    ),
    (
        r"\bcameras?\b",
        "camera",
    ),
    (
        r"\bprinters?\b",
        "printer",
    ),
]

        for pattern, category in category_patterns:
            if re.search(pattern, message):
                data["category"] = category
                break
        # --------------------------------------------------
        # Final mandatory-feature cleanup after category normalization.
        # Product types belong in category/keywords, not must_have_features.
        # Keep genuine features such as "wireless" and "noise cancellation".
        # --------------------------------------------------
        normalized_features = []

        for feature in data.get("must_have_features") or []:
            feature = str(feature).strip().lower()

            if not feature:
                continue

            if feature in invalid_features or feature in product_type_features:
                continue

            if feature not in normalized_features:
                normalized_features.append(feature)

        data["must_have_features"] = normalized_features

        # --------------------------------------------------
        # 6. Normalize common brand names
        # --------------------------------------------------

        known_brands = [
            "Sony",
            "Samsung",
            "Apple",
            "Dell",
            "HP",
            "Lenovo",
            "Logitech",
            "JBL",
            "Bose",
            "Asus",
            "Acer",
        ]

        for brand in known_brands:
            if re.search(
                r"\b" + re.escape(brand) + r"\b",
                message,
                re.IGNORECASE,
            ):
                data["brand"] = brand
                break

        # --------------------------------------------------
        # 7. Detect greetings and general questions
        # --------------------------------------------------

        normalized_message = re.sub(r"\s+", " ", message).strip(" .!?,")

        # These are deliberately narrow patterns so shopping requests
        # containing a greeting are not accidentally classified as general.
        greeting_patterns = [
            r"^(?:hi|hello|hey|good morning|good afternoon|good evening)$",
            r"^(?:hello|hi|hey)[, ]+(?:what can you help me with|"
            r"what can you do|who are you)$",
            r"^(?:what can you help me with|what can you do|who are you)$",
        ]

        if any(
            re.fullmatch(pattern, normalized_message)
            for pattern in greeting_patterns
        ):
            data["intent"] = "general_question"
            data["keywords"] = []
            data["category"] = None
            data["brand"] = None
            data["min_price"] = None
            data["max_price"] = None
            data["currency"] = None
            data["min_rating"] = None
            data["only_available"] = True
            data["must_have_features"] = []
            data["sort_by"] = "relevance"

        # --------------------------------------------------
        # 8. Normalize search keywords
        # --------------------------------------------------

        # Price and rating constraints are represented by structured fields.
        # Remove them from free-text keywords to avoid noisy search terms.
        normalized_keywords = []

        constraint_pattern = re.compile(
            r"\b(?:under|below|less than|up to|at most|maximum|max(?:imum)?"
            r"(?: price of)?|over|above|more than|at least|minimum"
            r"(?: price of)?)\s*"
            r"[$₹€£]?\s*\d[\d,]*(?:\.\d+)?\s*"
            r"(?:dollars?|usd|rupees?|inr|euros?|eur|pounds?|gbp)?\b",
            re.IGNORECASE,
        )

        rating_words_pattern = re.compile(
            r"\b(?:highly rated|best[- ]rated|highest rated|top[- ]rated|"
            r"good rating|best rating|best rated|ratings?|rated|stars?)\b",
            re.IGNORECASE,
        )

        for keyword in data.get("keywords") or []:
            cleaned = str(keyword).lower().strip()
            cleaned = constraint_pattern.sub(" ", cleaned)
            cleaned = rating_words_pattern.sub(" ", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_,.;:")

            if not cleaned:
                continue

            if cleaned not in normalized_keywords:
                normalized_keywords.append(cleaned)

        # Keep explicit product category and requested features searchable.
        for term in [data.get("category"), *(data.get("must_have_features") or [])]:
            if term:
                cleaned = re.sub(r"\s+", " ", str(term).lower()).strip()
                if cleaned and cleaned not in normalized_keywords:
                    normalized_keywords.append(cleaned)

        data["keywords"] = normalized_keywords

        return ShoppingRequirements.model_validate(data)

    # ------------------------------------------------------
    # 5. MERGE PREVIOUS AND NEW REQUIREMENTS
    # ------------------------------------------------------

    def merge_requirements(
        self,
        previous_requirements: dict,
        new_requirements: ShoppingRequirements,
        user_message: str = "",
    ) -> ShoppingRequirements:
        """
        Merge previous shopping requirements with new requirements.

        Explicitly removed filters are not restored.
        Unchanged filters are preserved across related shopping requests.
        """

        if not isinstance(new_requirements, ShoppingRequirements):
            raise ValueError(
                "New requirements must be a valid ShoppingRequirements object."
            )

        previous = previous_requirements or {}
        current = new_requirements.model_dump()

        message = user_message.lower().strip()

        # Do not merge shopping filters into unrelated questions.
        if current["intent"] in (
            "general_question",
            "out_of_scope",
            "clarification_needed",
        ):
            return new_requirements

        # --------------------------------------------------
        # 1. Detect explicit budget removal
        # --------------------------------------------------

        remove_budget_phrases = [
            "remove my budget",
            "remove the budget",
            "remove budget",
            "no budget limit",
            "without a budget",
            "without budget",
            "any price",
            "no price limit",
            "remove price limit",
            "remove the price limit",
            "unlimited budget",
            "ignore my budget",
            "ignore the budget",
        ]

        remove_budget = any(
            phrase in message
            for phrase in remove_budget_phrases
        )

        # --------------------------------------------------
        # 2. Detect explicit brand removal
        # --------------------------------------------------

        remove_brand_phrases = [
            "show all brands",
            "all brands",
            "remove brand filter",
            "remove the brand filter",
            "remove brand",
            "any brand",
            "any brands",
            "without brand",
        ]

        remove_brand = any(
            phrase in message
            for phrase in remove_brand_phrases
        )

        # --------------------------------------------------
        # 3. Detect explicit rating removal
        # --------------------------------------------------

        remove_rating_phrases = [
            "remove rating filter",
            "remove the rating filter",
            "remove minimum rating",
            "any rating",
            "ignore rating",
        ]

        remove_rating = any(
            phrase in message
            for phrase in remove_rating_phrases
        )

        # --------------------------------------------------
        # 4. Detect explicit feature removal
        # --------------------------------------------------

        remove_feature_phrases = [
            "remove feature",
            "remove this feature",
            "remove that feature",
            "without this feature",
            "without that feature",
            "remove the feature",
        ]

        remove_feature = any(
            phrase in message
            for phrase in remove_feature_phrases
        )

        # --------------------------------------------------
        # 5. Preserve or remove budget
        # --------------------------------------------------

        if remove_budget:
            current["min_price"] = None
            current["max_price"] = None
            current["currency"] = None

        else:
            if current.get("min_price") is None:
                current["min_price"] = previous.get("min_price")

            if current.get("max_price") is None:
                current["max_price"] = previous.get("max_price")

            if current.get("currency") is None:
                current["currency"] = previous.get("currency")

        # --------------------------------------------------
        # 6. Preserve or remove brand
        # --------------------------------------------------

        if remove_brand:
            current["brand"] = None

        elif current.get("brand") is None:
            current["brand"] = previous.get("brand")

        # --------------------------------------------------
        # 7. Preserve category unless the user changes it
        # --------------------------------------------------

        message = user_message.lower().strip()

        budget_removal_phrases = [
            "remove my budget",
            "remove the budget",
            "remove budget",
            "no budget limit",
            "without a budget",
            "without budget",
            "any price",
            "no price limit",
            "remove price limit",
            "remove the price limit",
            "unlimited budget",
        ]

        is_budget_removal = any(
            phrase in message
            for phrase in budget_removal_phrases
        )

        # Preserve the old category only when the current message does not
        # explicitly name a new product category. This allows requests such
        # as "remove my budget and show laptops" to change the category.
        category_patterns = [
            r"\\b(?:headphones?|headsets?)\\b",
            r"\\b(?:laptops?|notebooks)\\b",
            r"\\b(?:smartphones?|mobile phones?|mobiles)\\b",
            r"\\bkeyboards?\\b",
            r"\\b(?:mice|computer mouse)\\b",
            r"\\b(?:monitors?|computer screens?)\\b",
            r"\\b(?:tablets?|ipad)\\b",
            r"\\b(?:televisions?|tvs?)\\b",
            r"\\bcameras?\\b",
            r"\\bprinters?\\b",
            r"\\bspeakers?\\b",
            r"\\b(?:smartwatches?|watches)\\b",
        ]
        category_explicit = any(
            re.search(pattern, message)
            for pattern in category_patterns
        )

        if not category_explicit and (
            is_budget_removal or current.get("category") is None
        ):
            current["category"] = previous.get("category")

        # --------------------------------------------------
        # 8. Preserve or remove minimum rating
        # --------------------------------------------------

        if remove_rating:
            current["min_rating"] = None

        elif current.get("min_rating") is None:
            current["min_rating"] = previous.get("min_rating")

        # --------------------------------------------------
        # 9. Preserve keywords
        # --------------------------------------------------

        # Filter-removal messages often produce noisy LLM keywords such as
        # "budget", "minimum", or "electronics". If the user is only removing
        # a budget and has not introduced a new category/brand, retain the
        # previous search keywords instead of searching for those words.
        if not current.get("keywords") or (
            remove_budget
            and not category_explicit
            and current.get("brand") == previous.get("brand")
        ):
            current["keywords"] = previous.get("keywords", [])

        # --------------------------------------------------
        # 10. Preserve or remove required features
        # --------------------------------------------------

        if remove_feature:
            current["must_have_features"] = []

        elif not current.get("must_have_features"):
            current["must_have_features"] = previous.get(
                "must_have_features",
                [],
            )

        # --------------------------------------------------
        # 11. Preserve sorting unless the user explicitly changes it
        # --------------------------------------------------

        explicit_rating_sort = any(
            phrase in message
            for phrase in (
                "highest rated",
                "best rated",
                "best-rated",
                "top rated",
                "top-rated",
                "highly rated",
                "good rating",
                "best rating",
                "sort by rating",
                "highest rating first",
            )
        )

        explicit_price_ascending = any(
            phrase in message
            for phrase in (
                "cheapest",
                "lowest price",
                "price low to high",
            )
        )

        explicit_price_descending = any(
            phrase in message
            for phrase in (
                "most expensive",
                "highest price",
                "price high to low",
            )
        )

        if explicit_price_ascending:
            current["sort_by"] = "price_ascending"
        elif explicit_price_descending:
            current["sort_by"] = "price_descending"
        elif explicit_rating_sort:
            current["sort_by"] = "rating"
        else:
            current["sort_by"] = previous.get(
                "sort_by",
                current.get("sort_by", "relevance"),
            )

        # --------------------------------------------------
        # 12. Validate final merged requirements
        # --------------------------------------------------
        
        return ShoppingRequirements.model_validate(current)