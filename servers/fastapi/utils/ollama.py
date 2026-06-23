import json
import logging
import re
from collections.abc import AsyncGenerator
from urllib.parse import urlsplit

import aiohttp
from fastapi import HTTPException

from constants.supported_ollama_models import SUPPORTED_OLLAMA_MODELS
from models.ollama_model_status import OllamaModelStatus
from utils.get_env import get_ollama_url_env

LOGGER = logging.getLogger(__name__)

def _extract_ollama_parameter_suffix(model_ref: str) -> str:
    suffix_match = re.search(
        r":((?:[0-9]+(?:\.[0-9]+)?(?:x[0-9]+(?:\.[0-9]+)?)?)b)\b",
        model_ref,
        re.IGNORECASE,
    )
    if suffix_match:
        return suffix_match.group(1).upper()
    return ""


def _build_ollama_library_models() -> list[dict]:
    models: list[dict] = []
    for model_id, metadata in sorted(SUPPORTED_OLLAMA_MODELS.items()):
        parameters = _extract_ollama_parameter_suffix(model_id)
        models.append(
            {
                "name": metadata.value,
                "description": metadata.label,
                "parameters": parameters if parameters else None,
                "size": metadata.size,
            }
        )
    return models


OLLAMA_LIBRARY_MODELS = _build_ollama_library_models()


def _get_ollama_url(ollama_url: str | None = None) -> str:
    raw_url = (ollama_url or get_ollama_url_env() or "http://localhost:11434").strip()
    if not raw_url:
        raw_url = "http://localhost:11434"
    if "://" not in raw_url:
        raw_url = f"http://{raw_url}"

    split_result = urlsplit(raw_url)
    if split_result.scheme not in {"http", "https"} or not split_result.netloc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Ollama URL. Use a valid http:// or https:// URL.",
        )

    return raw_url.rstrip("/")


def _ollama_unreachable_error(ollama_url: str | None = None) -> HTTPException:
    resolved_ollama_url = _get_ollama_url(ollama_url)
    return HTTPException(
        status_code=503,
        detail=(
            f"Could not connect to Ollama at {resolved_ollama_url}. "
            "Make sure Ollama is running and reachable from Presenton. "
            "When Presenton runs in Docker, use host.docker.internal instead of localhost."
        ),
    )


def _ollama_bad_response_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail=f"Ollama returned an unexpected response: {message}",
    )


def _extract_ollama_parameter_count(model_name: str, model_details: dict | None = None) -> str:
    details = model_details or {}
    details_parameter_size = details.get("parameter_size")
    if isinstance(details_parameter_size, str) and details_parameter_size.strip():
        return details_parameter_size.strip().upper()

    parameters_from_name = _extract_ollama_parameter_suffix(model_name)
    if parameters_from_name:
        return parameters_from_name

    supported_model = SUPPORTED_OLLAMA_MODELS.get(model_name.lower())
    if supported_model:
        return _extract_ollama_parameter_suffix(supported_model.value)
    return ""


async def list_available_ollama_models(
    ollama_url: str | None = None,
) -> list[OllamaModelStatus]:
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(
                f"{_get_ollama_url(ollama_url)}/api/tags",
            ) as response:
                if response.status == 200:
                    try:
                        pulled_models = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, json.JSONDecodeError, ValueError) as error:
                        raise _ollama_bad_response_error(
                            "the /api/tags response was not valid JSON"
                        ) from error

                    models = (
                        pulled_models.get("models")
                        if isinstance(pulled_models, dict)
                        else None
                    )
                    if not isinstance(models, list):
                        raise _ollama_bad_response_error(
                            "the /api/tags response did not include a models list"
                        )

                    available_models: list[OllamaModelStatus] = []
                    for model in models:
                        if not isinstance(model, dict):
                            continue
                        name = model.get("model") or model.get("name")
                        if not isinstance(name, str) or not name.strip():
                            continue
                        size = model.get("size") if isinstance(model.get("size"), int) else 0
                        available_models.append(
                            OllamaModelStatus(
                                name=name,
                                parameters=_extract_ollama_parameter_count(
                                    name,
                                    model.get("details")
                                    if isinstance(model.get("details"), dict)
                                    else None,
                                )
                                or None,
                                size=size,
                                status="pulled",
                                downloaded=size,
                                done=True,
                            )
                        )
                    return available_models
                elif response.status == 403:
                    raise HTTPException(
                        status_code=403,
                        detail="Forbidden: Please check your Ollama Configuration",
                    )
                else:
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Failed to list Ollama models: {response.status}",
                    )
    except (aiohttp.ClientError, TimeoutError, OSError) as error:
        raise _ollama_unreachable_error(ollama_url) from error


def get_ollama_library_models() -> list[dict]:
    return OLLAMA_LIBRARY_MODELS


async def pull_ollama_model(
    model_name: str,
    ollama_url: str | None = None,
) -> AsyncGenerator[str, None]:
    base_url = _get_ollama_url(ollama_url)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None)
        ) as session:
            async with session.post(
                f"{base_url}/api/pull",
                json={"name": model_name, "stream": True, "insecure": False},
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    yield f"event: error\ndata: {json.dumps({'detail': body or 'Pull failed'})}\n\n"
                    return

                async for line in response.content:
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if not decoded:
                        continue
                    try:
                        data = json.loads(decoded)
                    except json.JSONDecodeError:
                        continue

                    if data.get("error"):
                        yield f"event: error\ndata: {json.dumps({'detail': data['error']})}\n\n"
                        return

                    if data.get("status") == "success":
                        yield f"event: response\ndata: {json.dumps({'type': 'complete', 'status': 'success', 'model': model_name})}\n\n"
                        return

                    total = data.get("total")
                    completed = data.get("completed")
                    status = data.get("status", "")

                    if total and completed is not None:
                        progress = round((completed / total) * 100, 1)
                        yield (
                            f"event: response\ndata: "
                            f"{json.dumps({'type': 'progress', 'status': status, 'total': total, 'completed': completed, 'progress': progress})}\n\n"
                        )
                    else:
                        yield (
                            f"event: response\ndata: "
                            f"{json.dumps({'type': 'status', 'status': status})}\n\n"
                        )
    except HTTPException as error:
        yield f"event: error\ndata: {json.dumps({'detail': error.detail})}\n\n"
    except (aiohttp.ClientError, TimeoutError, OSError) as error:
        LOGGER.error("Ollama pull error: %s", error)
        yield f"event: error\ndata: {json.dumps({'detail': f'Could not connect to Ollama at {base_url}'})}\n\n"
