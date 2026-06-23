import asyncio

import aiohttp
import pytest
from fastapi import HTTPException

from utils import ollama


class _FailingRequest:
    async def __aenter__(self):
        raise aiohttp.ClientConnectionError("connection refused")

    async def __aexit__(self, *_args):
        return False


class _FailingClientSession:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def get(self, *_args, **_kwargs):
        return _FailingRequest()


class _ResponseRequest:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args):
        return False


class _MalformedTagsResponse:
    status = 200
    reason = "OK"

    async def json(self, *_args, **_kwargs):
        return {"unexpected": []}


class _MalformedTagsClientSession:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def get(self, *_args, **_kwargs):
        return _ResponseRequest(_MalformedTagsResponse())


def test_list_models_returns_service_unavailable_when_ollama_is_unreachable(
    monkeypatch,
):
    monkeypatch.setenv("OLLAMA_URL", "http://host.docker.internal:11434/")
    monkeypatch.setattr(ollama.aiohttp, "ClientSession", _FailingClientSession)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ollama.list_available_ollama_models("http://ollama.example:11434/"))

    assert exc_info.value.status_code == 503
    assert "http://ollama.example:11434" in exc_info.value.detail
    assert "instead of localhost" in exc_info.value.detail


def test_list_models_rejects_malformed_ollama_tags_payload(monkeypatch):
    monkeypatch.setattr(ollama.aiohttp, "ClientSession", _MalformedTagsClientSession)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ollama.list_available_ollama_models("ollama.example:11434"))

    assert exc_info.value.status_code == 502
    assert "models list" in exc_info.value.detail
