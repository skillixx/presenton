import logging

from fastapi import HTTPException
from openai import APIError as OpenAIAPIError
from google.genai.errors import APIError as GoogleAPIError

from llmai.shared.errors import BaseError as LLMAIBaseError
from utils.image_generation_error import openai_error_detail

LOGGER = logging.getLogger(__name__)


def _provider_status_code(status_code: int | None) -> int:
    if status_code in {401, 403, 402, 404, 408, 409, 422, 429}:
        return status_code
    if status_code in {503, 504}:
        return status_code
    if status_code is not None and 400 <= status_code < 500:
        return 400
    if status_code is not None and status_code >= 500:
        return 502
    return 502


def _message_text(error: Exception) -> str:
    message = getattr(error, "message", None)
    if isinstance(message, str) and message.strip():
        return message.strip()
    return str(error)


def _friendly_provider_detail(message: str, *, operation: str) -> str:
    lower_message = message.lower()
    if "api quota is unavailable" in lower_message:
        return message
    if "not supported" in lower_message and "model" in lower_message:
        return (
            "Configured LLM model is not supported by this provider/account. "
            "Select a supported model and try again."
        )
    if "quota" in lower_message or "rate limit" in lower_message:
        return (
            "The LLM provider rejected the request because of quota or rate limits. "
            "Check billing/limits or try again later."
        )
    if "credit" in lower_message or "requires more credits" in lower_message:
        return (
            "The LLM provider rejected the request because the account needs more "
            "credits or a smaller token request."
        )
    if "authentication" in lower_message or "api key" in lower_message:
        return "The LLM provider credentials are invalid or expired."
    if "degraded function" in lower_message or "function id" in lower_message:
        return (
            "The configured provider tool/function is unavailable. Refresh the "
            "provider configuration or retry without that tool."
        )
    if "invalid json schema" in lower_message or "schema" in lower_message:
        return (
            "The provider rejected the generated response schema. Try a different "
            "model/provider or simplify the request."
        )
    if "timed out" in lower_message or "timeout" in lower_message:
        return "The LLM provider request timed out. Please try again."
    if "connection error" in lower_message or "connection" in lower_message:
        return "Could not connect to the LLM provider. Check the provider URL/network."
    if operation == "Google API request":
        return f"Google API error: {message}"
    return f"{operation} failed: {message}"


def handle_llm_client_exceptions(e: Exception) -> HTTPException:
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, LLMAIBaseError):
        return HTTPException(status_code=e.status_code, detail=e.message)
    if isinstance(e, OpenAIAPIError):
        status_code = getattr(e, "status_code", None)
        error_type = e.__class__.__name__
        if error_type == "APIConnectionError":
            status_code = 503
        elif error_type == "APITimeoutError":
            status_code = 504
        raw_detail = openai_error_detail(e, operation="API request")
        return HTTPException(
            status_code=_provider_status_code(status_code),
            detail=_friendly_provider_detail(raw_detail, operation="OpenAI API request"),
        )
    if isinstance(e, GoogleAPIError):
        status_code = (
            getattr(e, "code", None)
            or getattr(e, "status_code", None)
            or getattr(e, "status", None)
        )
        return HTTPException(
            status_code=_provider_status_code(status_code),
            detail=_friendly_provider_detail(
                _message_text(e),
                operation="Google API request",
            ),
        )

    LOGGER.exception("Unhandled LLM client error")
    return HTTPException(status_code=500, detail=f"LLM API error: {e}")
