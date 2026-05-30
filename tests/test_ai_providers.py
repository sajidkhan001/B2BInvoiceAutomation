from __future__ import annotations

import pytest

from b2bdoc.ai.providers import AIProviderClient, AIProviderError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_openai_model_listing_uses_models_endpoint():
    session = FakeSession(FakeResponse(200, {"data": [{"id": "gpt-test"}]}))
    models = AIProviderClient("openai", "key", session=session).list_models()
    assert models[0].id == "gpt-test"
    assert session.calls[0][0] == "https://api.openai.com/v1/models"
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer key"


def test_anthropic_model_listing_uses_versioned_models_endpoint():
    session = FakeSession(FakeResponse(200, {"data": [{"id": "claude-test", "display_name": "Claude Test"}]}))
    models = AIProviderClient("anthropic", "key", session=session).list_models()
    assert models[0].display_name == "Claude Test"
    assert session.calls[0][0] == "https://api.anthropic.com/v1/models"
    assert session.calls[0][1]["headers"]["anthropic-version"] == "2023-06-01"


def test_model_listing_reports_invalid_key_or_offline_state():
    session = FakeSession(FakeResponse(401, {"error": "bad key"}))
    with pytest.raises(AIProviderError):
        AIProviderClient("openai", "bad", session=session).list_models()
