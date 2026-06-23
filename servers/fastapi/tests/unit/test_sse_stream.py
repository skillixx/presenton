import asyncio
import logging

from fastapi import HTTPException

from utils.sse_stream import stream_with_terminal_errors


def test_stream_with_terminal_errors_emits_terminal_sse_for_http_exception():
    async def failing_stream():
        yield "event: response\ndata: {}\n\n"
        raise HTTPException(status_code=429, detail="Provider quota exceeded")

    async def collect():
        return [
            chunk
            async for chunk in stream_with_terminal_errors(
                failing_stream(),
                logging.getLogger(__name__),
                context="test",
            )
        ]

    chunks = asyncio.run(collect())

    assert chunks[0] == "event: response\ndata: {}\n\n"
    assert '"type": "error"' in chunks[1]
    assert "Provider quota exceeded" in chunks[1]
