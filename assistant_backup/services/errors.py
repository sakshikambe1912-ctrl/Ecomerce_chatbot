"""Errors raised by the chat flow. Each has a stable code and a user-safe message."""


class ChatError(Exception):
    code = "internal_error"
    status = 500
    default_message = "EcommerceAI could not process your request. Please try again."

    def __init__(self, message=None):
        self.message = message or self.default_message
        super().__init__(self.message)


class WebsiteUnavailableError(ChatError):
    code = "website_unavailable"
    status = 400
    default_message = "One or more requested websites do not exist or are inactive."


class ConversationNotFoundError(ChatError):
    code = "conversation_not_found"
    status = 404
    default_message = "Conversation not found or website scope does not match."


class ModelUnavailableError(ChatError):
    code = "model_unavailable"
    status = 503
    default_message = (
        "The AI model is not reachable right now. Please try again in a moment."
    )
