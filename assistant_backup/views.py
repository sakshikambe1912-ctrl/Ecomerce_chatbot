import logging

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from assistant.serializers import ChatRequestSerializer
from assistant.services.chat_orchestrator import ChatError, ChatOrchestrator
from assistant.session import get_owner_key

logger = logging.getLogger(__name__)


def error_response(message, code, http_status, **extra):
    """Every error uses the same shape: {"error": <safe message>, "code": <snake_case>}."""
    return Response({"error": message, "code": code, **extra}, status=http_status)


class ChatAPIView(APIView):
    """POST /api/chat/ — validates the request and delegates to ChatOrchestrator."""

    # Anonymous, session-owned conversations: no Django user login. Without
    # SessionAuthentication DRF does not enforce CSRF; the endpoint only
    # accepts JSON, which a cross-site HTML form cannot send.
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "chat"

    def handle_exception(self, exc):
        # Give DRF's own errors (bad JSON, unsupported media type, throttling)
        # the same {"error", "code"} shape as every other chat error.
        response = super().handle_exception(exc)
        if isinstance(exc, exceptions.Throttled):
            response.data = {
                "error": "Too many requests. Please wait a moment and try again.",
                "code": "rate_limited",
            }
        elif isinstance(exc, exceptions.APIException) and response.status_code < 500:
            response.data = {"error": "Invalid request.", "code": "invalid_request"}
        return response

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "Invalid request.", "invalid_request", status.HTTP_400_BAD_REQUEST,
                details=serializer.errors,
            )

        data = serializer.validated_data
        try:
            result = ChatOrchestrator().handle(
                owner_key=get_owner_key(request),
                message=data["message"],
                website_ids=data["website_ids"],
                conversation_id=data.get("conversation_id"),
            )
        except ChatError as exc:
            if exc.status >= 500:
                logger.warning("Chat request failed (%s).", exc.code)
            return error_response(exc.message, exc.code, exc.status)
        except Exception:
            # The real exception is logged server-side only; the client never
            # sees a stack trace or provider payload.
            logger.exception("Unexpected error while processing an EcommerceAI chat request.")
            return error_response(
                "EcommerceAI could not process your request. Please try again.",
                "internal_error",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(result.as_response(), status=status.HTTP_200_OK)
