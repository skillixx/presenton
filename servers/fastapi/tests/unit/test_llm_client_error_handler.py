from utils.llm_client_error_handler import (
    _friendly_provider_detail,
    _provider_status_code,
)


def test_provider_status_code_preserves_actionable_client_errors():
    assert _provider_status_code(429) == 429
    assert _provider_status_code(401) == 401
    assert _provider_status_code(404) == 404


def test_provider_status_code_maps_upstream_server_errors_to_bad_gateway():
    assert _provider_status_code(500) == 502
    assert _provider_status_code(524) == 502
    assert _provider_status_code(None) == 502


def test_friendly_provider_detail_classifies_common_provider_failures():
    assert "not supported" in _friendly_provider_detail(
        "The gpt-5.1-codex-mini model is not supported",
        operation="OpenAI API request",
    )
    assert "quota or rate limits" in _friendly_provider_detail(
        "You exceeded your current quota",
        operation="OpenAI API request",
    )
    assert "response schema" in _friendly_provider_detail(
        "invalid JSON schema in format",
        operation="OpenAI API request",
    )
