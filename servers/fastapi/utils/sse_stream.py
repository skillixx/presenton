import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Optional

from fastapi import HTTPException

from models.sse_response import SSEErrorResponse


def http_exception_detail(error: HTTPException) -> str:
    detail = error.detail
    if isinstance(detail, str):
        return detail
    return str(detail)


async def stream_with_terminal_errors(
    stream: AsyncIterator[str],
    logger: logging.Logger,
    *,
    context: Optional[str] = None,
) -> AsyncIterator[str]:
    """Convert post-start stream failures into terminal SSE error events."""
    try:
        async for chunk in stream:
            yield chunk
    except asyncio.CancelledError:
        logger.info("SSE client disconnected%s", f": {context}" if context else "")
        raise
    except HTTPException as error:
        yield SSEErrorResponse(detail=http_exception_detail(error)).to_string()
    except Exception:
        logger.exception(
            "Unhandled SSE stream error%s",
            f": {context}" if context else "",
        )
        yield SSEErrorResponse(
            detail="The stream failed while processing this request. Please try again.",
        ).to_string()
