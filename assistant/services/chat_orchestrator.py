"""
The whole chat flow. assistant/views.py only validates input and maps errors.

Order of work:
1. validate the selected websites;
2. load the conversation (a new one is NOT saved yet) and its last messages;
3. run all model and search work with no database transaction open;
4. open ONE short transaction that creates the conversation if needed, saves
   the user and assistant messages and updates the conversation memory.

If anything fails before step 4, nothing is written.
"""
import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils.timesince import timesince

from assistant.services.errors import (  # noqa: F401 (re-exported for the view)
    ChatError,
    ConversationNotFoundError,
    ModelUnavailableError,
    WebsiteUnavailableError,
)
from assistant.services.alternatives_service import find_alternatives, render_alternatives
from assistant.services.answer_validator import validate_answer
from assistant.services.comparison_service import (
    ComparisonService,
    build_comparison,
    is_comparison_request,
    mentions_compared_product,
    render_comparison,
)
from assistant.services.conversation_context import is_follow_up, is_listing_request, might_follow_up
from assistant.services.currency_policy import currency_from_reply, decide_currency
from assistant.services.grounded_response_service import GroundedResponseService
from assistant.services.hybrid_search_service import HybridSearchService
from assistant.services.product_lookup import facts_answer, find_named_products
from assistant.services.product_search_service import (
    ProductSearchService,
    category_matches,
    searchable_fields,
)
from assistant.services.requirements_service import RequirementsService, ShoppingRequirements
from assistant.services.scope_guard import GREETING_REPLY, OUT_OF_SCOPE_REPLY
from assistant.services.search_diagnostics import build_no_match_message
from assistant.services.scope_guard import check as scope_check
from assistant.services.shopping_advice_service import ShoppingAdviceService
from conversations.models import Conversation, Message
from products.models import Product
from websites.models import Website

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10
SEARCH_LIMIT = 20
# Alternatives are looked for only when fewer matches than this were found.
ALTERNATIVES_BELOW = 3
SHOPPING_INTENTS = ("product_search", "product_comparison")
# At most this many product cards are shown under one answer.
MAX_CARDS = 8
SEMANTIC_UNAVAILABLE_NOTICE = "Semantic ranking was unavailable; results use standard ranking."


def _products_named_in_answer(answer, products):
    """Products whose name (first three words of the title) appears in the answer."""
    text = (answer or "").lower()
    named = []
    for product in products:
        key = " ".join((product.get("title") or "").lower().split()[:3])
        if key and key in text:
            named.append(product)
    return named


def _has_hard_limits(requirements):
    return any([
        requirements.min_price is not None,
        requirements.max_price is not None,
        requirements.min_rating is not None,
        requirements.must_have_features,
    ])


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ChatResult:
    message: str
    intent: str
    answer: str
    requirements: dict = field(default_factory=dict)
    products: list = field(default_factory=list)
    alternatives: list = field(default_factory=list)
    comparison: dict | None = None
    website_freshness: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    # Requirements to store as conversation memory (None leaves memory unchanged).
    remember: dict | None = None
    conversation: Conversation | None = None

    def as_response(self):
        return {
            "conversation_id": self.conversation.id if self.conversation else None,
            "message": self.message,
            "intent": self.intent,
            "answer": self.answer,
            "requirements": self.requirements,
            "total_products": len(self.products),
            "products": self.products,
            "alternatives": self.alternatives,
            "comparison": self.comparison,
            "website_freshness": self.website_freshness,
            "notices": self.notices,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class ChatOrchestrator:

    def handle(self, owner_key, message, website_ids, conversation_id=None):
        website_ids = sorted(set(website_ids))
        websites = list(Website.objects.filter(id__in=website_ids, is_active=True))
        if len(websites) != len(website_ids):
            raise WebsiteUnavailableError()

        conversation = self._load_conversation(owner_key, conversation_id, website_ids)
        history = self._history(conversation)
        previous = dict(conversation.current_requirements or {}) if conversation else {}

        freshness, stale_notices = self._freshness(websites)
        stale_ids = [f["website_id"] for f in freshness if f["stale"]]

        # All model and search work happens here, outside any transaction.
        result = self._respond(message, website_ids, history, previous, stale_ids)

        result.website_freshness = freshness
        if stale_notices and result.intent in SHOPPING_INTENTS:
            result.notices.extend(stale_notices)
            result.answer = result.answer.rstrip() + "\n\n" + " ".join(stale_notices)

        result.conversation = self._save(owner_key, conversation, website_ids, message, result)
        return result

    # -- loading -------------------------------------------------------------

    def _load_conversation(self, owner_key, conversation_id, website_ids):
        if conversation_id is None:
            return None
        # Another owner's conversation is reported as not found (never 403).
        conversation = Conversation.objects.filter(id=conversation_id, owner_key=owner_key).first()
        if conversation is None or sorted(conversation.website_scope) != website_ids:
            raise ConversationNotFoundError()
        return conversation

    @staticmethod
    def _freshness(websites):
        """Freshness of each selected website and a notice for stale or never-synced data."""
        freshness, notices = [], []
        for website in sorted(websites, key=lambda w: w.id):
            stale = website.is_stale()
            freshness.append({
                "website_id": website.id,
                "website_name": website.name,
                "last_synced_at": website.last_synced_at.isoformat() if website.last_synced_at else None,
                "stale": stale,
            })
            if website.last_synced_at is None:
                notices.append(f"Data for {website.name} has never been synced.")
            elif stale:
                notices.append(f"Data for {website.name} was last updated {timesince(website.last_synced_at)} ago.")
        return freshness, notices

    def _history(self, conversation):
        if conversation is None:
            return []
        messages = conversation.messages.order_by("-created_at", "-id").values("role", "content")
        return list(messages[:HISTORY_LIMIT])[::-1]

    # -- the turn ------------------------------------------------------------

    def _respond(self, message, website_ids, history, previous, stale_ids=()):
        # Deterministic scope check before any model call. Memory is untouched.
        verdict = scope_check(message)
        if verdict == "out_of_scope":
            return ChatResult(message=message, intent="out_of_scope", answer=OUT_OF_SCOPE_REPLY)
        if verdict == "greeting":
            return ChatResult(message=message, intent="general_question", answer=GREETING_REPLY)

        pending = previous.pop("awaiting", None)
        options = previous.pop("currency_options", [])

        # The previous turn asked which currency to use; a reply that names one
        # of the offered currencies resumes that search without a model call.
        chosen = currency_from_reply(message, options) if pending == "currency" else None
        follow_up = False
        if chosen:
            requirements = ShoppingRequirements.model_validate({**previous, "currency": chosen})
            follow_up = True
        else:
            requirements, follow_up = self._extract(message, history, previous)
        requirements = self._trust_catalog(requirements, website_ids)

        # Neither general questions nor out-of-scope requests change memory.
        if requirements.intent in ("general_question", "clarification_needed"):
            # A question about a product the user names is answered from the catalog.
            exact, loose = find_named_products(message, website_ids)
            if exact or loose:
                return self._answer_about(message, exact or loose, requirements)

        if requirements.intent == "general_question":
            return ChatResult(
                message=message,
                intent="general_question",
                answer=ShoppingAdviceService().answer(message),
            )

        if requirements.intent == "out_of_scope":
            return ChatResult(message=message, intent="out_of_scope", answer=OUT_OF_SCOPE_REPLY)

        if requirements.intent == "clarification_needed":
            return ChatResult(
                message=message,
                intent="clarification_needed",
                answer="Could you clarify what kind of product you're looking for?",
                requirements=requirements.model_dump(mode="json"),
            )

        decision = decide_currency(requirements, website_ids)
        if decision.clarification:
            # Keep the shopping request in memory so the reply can resume it.
            pending_memory = requirements.model_dump(mode="json")
            pending_memory.update(awaiting="currency", currency_options=decision.options)
            return ChatResult(
                message=message,
                intent="clarification_needed",
                answer=decision.clarification,
                requirements=requirements.model_dump(mode="json"),
                remember=pending_memory,
            )
        if decision.currency and not requirements.currency:
            requirements = requirements.model_copy(update={"currency": decision.currency})

        hybrid = HybridSearchService()
        products = None
        uncertain = False

        # Comparing products the user names: use exactly those products.
        if is_comparison_request(requirements, message):
            exact, _ = find_named_products(message, website_ids)
            if len(exact) >= 2:
                products = exact

        if products is None:
            # The user's own words guide the meaning-based part, except in follow-ups
            # ("increase my budget") and whole-catalog requests ("products under $50").
            query_text = None if (follow_up or is_listing_request(message)) else message
            products = hybrid.search(
                requirements=requirements,
                website_ids=website_ids,
                limit=SEARCH_LIMIT,
                query_text=query_text,
            )
            uncertain = hybrid.mode == "semantic"

            # Nothing found and no budget/rating limit to blame: the user may have
            # named a product the keyword search could not place.
            if not products and not _has_hard_limits(requirements):
                exact, loose = find_named_products(message, website_ids)
                if exact or loose:
                    return self._answer_about(message, exact or loose, requirements)

        notices = []
        if not hybrid.semantic_available:
            notices.append(SEMANTIC_UNAVAILABLE_NOTICE)

        cards = products[:MAX_CARDS]
        comparison = None
        if products and is_comparison_request(requirements, message):
            comparison = build_comparison(products, stale_ids)

        if comparison:
            answer = self._explain_comparison(message, comparison, products, requirements)
        elif products:
            answer = GroundedResponseService().generate_answer(
                user_message=message, products=products, uncertain=uncertain,
            )
            # Any price, rating or URL the records do not support -> template answer.
            answer, valid = validate_answer(answer, products, requirements)
            if not valid:
                logger.warning("Generated answer contained unsupported values; used the template answer.")
            # Cards: the products the answer is about. For closest-by-meaning results
            # that is only the ones the answer recommends (possibly none).
            named = _products_named_in_answer(answer, products)
            cards = named if (named or uncertain) else products[:MAX_CARDS]
        else:
            # Deterministic explanation; no model call and no non-matching products.
            stages = ProductSearchService().diagnose(requirements, website_ids)
            answer = build_no_match_message(requirements, stages)

        alternatives = []
        if len(products) < ALTERNATIVES_BELOW:
            alternatives = find_alternatives(requirements, website_ids, exclude_ids=[p["id"] for p in products])
            if alternatives:
                answer = answer.rstrip() + "\n\n" + render_alternatives(alternatives)

        requirements_json = requirements.model_dump(mode="json")
        return ChatResult(
            message=message,
            intent=requirements.intent,
            answer=answer,
            requirements=requirements_json,
            products=cards,
            alternatives=alternatives,
            comparison=comparison,
            notices=notices,
            remember=requirements_json,
        )

    @staticmethod
    def _explain_comparison(message, comparison, products, requirements):
        compared_ids = {row["id"] for row in comparison["products"]}
        compared = [p for p in products if p["id"] in compared_ids]
        explanation = ComparisonService().explain(message, comparison)
        # An explanation that names none of the compared products is not used.
        if explanation and mentions_compared_product(explanation, comparison):
            explanation, valid = validate_answer(explanation, compared, requirements)
            if valid:
                return explanation
            logger.warning("Comparison explanation contained unsupported values; used the computed comparison.")
        return render_comparison(comparison)

    def _extract(self, message, history, previous):
        """Returns (requirements, follow_up). Memory is merged only for real follow-ups."""
        requirements_service = RequirementsService()
        # The earlier conversation is shown to the model only when it could matter.
        seen_history = history if (previous and might_follow_up(message)) else []
        requirements = requirements_service.extract(
            user_message=message,
            conversation_history=seen_history,
        )
        follow_up = is_follow_up(message, requirements, previous)
        if follow_up:
            requirements = requirements_service.merge_requirements(
                previous_requirements=previous,
                new_requirements=requirements,
                user_message=message,
            )
        return requirements, follow_up

    @staticmethod
    def _trust_catalog(requirements, website_ids):
        """A product type the model invented ("home_appliances") is dropped, not enforced."""
        category = (requirements.category or "").strip()
        if not category:
            return requirements
        products = Product.objects.filter(website_id__in=website_ids, website__is_active=True)
        for product in products.iterator():
            if category_matches(searchable_fields(product), category):
                return requirements
        return requirements.model_copy(update={"category": None})

    @staticmethod
    def _answer_about(message, products, requirements):
        """Answer a question about specific, named catalog products."""
        requirements_json = requirements.model_dump(mode="json")
        if len(products) == 1:
            facts = facts_answer(message, products[0])
            if facts:
                return ChatResult(
                    message=message, intent="product_search", answer=facts,
                    requirements=requirements_json, products=products,
                )
        answer = GroundedResponseService().generate_answer(user_message=message, products=products)
        answer, valid = validate_answer(answer, products, requirements)
        if not valid:
            logger.warning("Generated answer contained unsupported values; used the template answer.")
        cards = _products_named_in_answer(answer, products) or products[:MAX_CARDS]
        return ChatResult(
            message=message, intent="product_search", answer=answer,
            requirements=requirements_json, products=cards,
        )

    # -- saving --------------------------------------------------------------

    def _save(self, owner_key, conversation, website_ids, message, result):
        with transaction.atomic():
            if conversation is None:
                conversation = Conversation.objects.create(
                    owner_key=owner_key,
                    title=message[:200],
                    website_scope=website_ids,
                    current_requirements={},
                )
            Message.objects.create(conversation=conversation, role="user", content=message)
            Message.objects.create(conversation=conversation, role="assistant", content=result.answer)

            if result.remember is not None:
                conversation.current_requirements = result.remember
            if conversation.title == "New conversation":
                conversation.title = message[:200]
            conversation.save(update_fields=["title", "current_requirements", "updated_at"])
        return conversation
