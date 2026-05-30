from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

from b2bdoc.models import ParsedDocument


class AIProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AIModel:
    id: str
    provider: str
    display_name: str


class AIProviderClient:
    def __init__(self, provider: str, api_key: str, session: requests.Session | None = None) -> None:
        self.provider = provider.lower().strip()
        self.api_key = api_key
        self.session = session or requests.Session()

    def list_models(self) -> list[AIModel]:
        if self.provider == "openai":
            return self._list_openai_models()
        if self.provider == "anthropic":
            return self._list_anthropic_models()
        raise AIProviderError(f"Unsupported AI provider: {self.provider}")

    def validate_key(self) -> bool:
        try:
            return bool(self.list_models())
        except AIProviderError:
            return False

    def _list_openai_models(self) -> list[AIModel]:
        response = self.session.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=20,
        )
        if response.status_code >= 400:
            raise AIProviderError(f"OpenAI model list failed: HTTP {response.status_code}")
        data = response.json().get("data", [])
        return sorted(
            [
                AIModel(id=item["id"], provider="openai", display_name=item["id"])
                for item in data
                if isinstance(item, dict) and item.get("id")
            ],
            key=lambda item: item.id,
        )

    def _list_anthropic_models(self) -> list[AIModel]:
        response = self.session.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise AIProviderError(f"Anthropic model list failed: HTTP {response.status_code}")
        data = response.json().get("data", [])
        return sorted(
            [
                AIModel(
                    id=item["id"],
                    provider="anthropic",
                    display_name=item.get("display_name") or item["id"],
                )
                for item in data
                if isinstance(item, dict) and item.get("id")
            ],
            key=lambda item: item.id,
        )


class ProviderAIFallback:
    """Optional extraction fallback. It never stores payloads or raw provider responses."""

    def __init__(self, provider: str, api_key: str, model: str, session: requests.Session | None = None) -> None:
        self.client = AIProviderClient(provider, api_key, session=session)
        self.provider = provider.lower().strip()
        self.model = model
        self.session = self.client.session

    def improve(
        self,
        parsed: ParsedDocument,
        payload: bytes,
        *,
        media_type: str,
        filename: str | None,
    ) -> ParsedDocument | None:
        if media_type != "application/pdf":
            return None
        prompt = (
            "Return only compact JSON corrections for a B2B document extraction. "
            "Allowed keys: document_number, issue_date, due_date, currency, subtotal, tax_total, total. "
            f"Current structured extraction: {parsed.model_dump_json(exclude={'line_items'})[:4000]}"
        )
        try:
            corrections = self._request_json(prompt)
        except AIProviderError:
            return None
        if not corrections:
            return None
        improved = parsed.model_copy(deep=True)
        for field_name in ["document_number", "issue_date", "due_date", "currency"]:
            value = corrections.get(field_name)
            if value:
                setattr(improved, field_name, str(value))
        for field_name in ["subtotal", "tax_total", "total"]:
            value = corrections.get(field_name)
            if value not in (None, ""):
                setattr(improved, field_name, value)
        improved.provenance.warnings.append(f"AI fallback used: {self.provider}")
        improved.validation_errors = [error for error in improved.validation_errors if "missing" not in error.lower()]
        improved.confidence = min(0.89, max(improved.confidence, improved.confidence + 0.10))
        improved.confidence_breakdown["ai_fallback"] = round(improved.confidence - parsed.confidence, 3)
        return improved

    def _request_json(self, prompt: str) -> dict[str, Any]:
        if self.provider == "openai":
            response = self.session.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.client.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "input": prompt,
                    "text": {"format": {"type": "json_object"}},
                },
                timeout=45,
            )
            if response.status_code >= 400:
                raise AIProviderError(f"OpenAI extraction failed: HTTP {response.status_code}")
            payload = response.json()
            text = payload.get("output_text") or _first_text(payload)
            return json.loads(text) if text else {}
        if self.provider == "anthropic":
            response = self.session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.client.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 800,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=45,
            )
            if response.status_code >= 400:
                raise AIProviderError(f"Anthropic extraction failed: HTTP {response.status_code}")
            text = "".join(
                item.get("text", "")
                for item in response.json().get("content", [])
                if isinstance(item, dict) and item.get("type") == "text"
            )
            return json.loads(text) if text else {}
        raise AIProviderError(f"Unsupported AI provider: {self.provider}")


def _first_text(payload: dict[str, Any]) -> str | None:
    for output in payload.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("text"):
                return content["text"]
    return None
