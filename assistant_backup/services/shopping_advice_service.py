"""
Answers general shopping and buying questions ("Is noise cancellation worth it
for flights?") that are not a search of the catalog.

The answer is labelled as general advice and must not make claims about
specific products, prices or stock.
"""
from assistant.services.llm_service import LLMService, call_llm
from assistant.services.scope_guard import OUT_OF_SCOPE_REPLY

ADVICE_LABEL = "General advice (not specific to products in the catalog):"

SYSTEM_PROMPT = (
    "You are EcommerceAI, a shopping assistant. Answer ONLY shopping and buying "
    "questions: what to look for, how features compare in general, how to choose. "
    "Do not name specific product models, prices, discounts or stock levels, and "
    "never claim anything about a particular store's catalog. Do not write code, "
    "essays, stories or anything unrelated to shopping. Keep the answer short "
    "(at most 6 sentences or a short '- ' list)."
)


class ShoppingAdviceService:
    def __init__(self):
        self.llm_service = LLMService()

    def answer(self, user_message):
        reply = call_llm(
            self.llm_service,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"{ADVICE_LABEL}\nQuestion: {user_message}",
                },
            ],
            temperature=0.3,
        )
        reply = (reply or "").strip()

        # A code block means the model drifted outside shopping help.
        if not reply or "```" in reply:
            return OUT_OF_SCOPE_REPLY

        if not reply.startswith(ADVICE_LABEL):
            reply = f"{ADVICE_LABEL}\n\n{reply}"
        return reply
