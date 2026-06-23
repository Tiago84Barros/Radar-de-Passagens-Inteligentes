"""OpenAI + web search provider — mesmo papel do GeminiSearchProvider.

Usa a Responses API da OpenAI com a ferramenta `web_search` para pesquisar
tarifas reais na web e responder no MESMO formato JSON estruturado do Gemini
(o system prompt, o schema Pydantic e a normalizacao sao herdados de
`gemini_search_provider` — um unico contrato para os dois motores de busca).

Chave: `OPENAI_API_KEY` (Streamlit secrets / env / GitHub Actions).
Sem dependencia de SDK: chama a API REST direto com `requests`.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from app.settings import get_settings
from providers.gemini_search_provider import (
    SYSTEM_PROMPT,
    GeminiSearchProvider,
    GeminiSearchProviderError,
)

logger = logging.getLogger(__name__)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

# Modelo principal + fallbacks (todos com suporte a web_search na Responses API).
DEFAULT_MODEL = "gpt-4o-mini"
FALLBACK_MODELS = ["gpt-4o", "gpt-4.1-mini"]

_TIMEOUT_SECONDS = 90


class OpenAISearchProviderError(GeminiSearchProviderError):
    """Erro do motor OpenAI — herda do erro Gemini para o manager tratar igual."""


class OpenAISearchProvider(GeminiSearchProvider):
    """Mesma interface/normalizacao do Gemini, trocando apenas o motor."""

    name = "openai_web_search"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.settings = get_settings()
        self.model = model

    def is_configured(self) -> bool:
        return bool(getattr(self.settings, "openai_api_key", None))

    # Sobrescreve a chamada de API; search_flights/normalize_response herdados.
    def _call_gemini(self, prompt: str) -> Any:  # noqa: D102 - nome herdado do fluxo base
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }

        last_err: Exception | None = None
        for model in [self.model, *FALLBACK_MODELS]:
            body = {
                "model": model,
                "instructions": SYSTEM_PROMPT,
                "input": prompt,
                "tools": [{"type": "web_search", "search_context_size": "high"}],
                "tool_choice": "required",
                "temperature": 0,
            }
            try:
                resp = requests.post(
                    OPENAI_RESPONSES_URL, json=body, headers=headers, timeout=_TIMEOUT_SECONDS
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = OpenAISearchProviderError(
                        f"HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                    logger.info("OpenAI %s indisponivel (%s); tentando proximo modelo.", model, resp.status_code)
                    continue
                if resp.status_code == 400 and "model" in resp.text.lower():
                    # Modelo inexistente nesta conta — tenta o proximo.
                    last_err = OpenAISearchProviderError(f"HTTP 400: {resp.text[:300]}")
                    continue
                resp.raise_for_status()
                return _extract_grounded_output(resp.json())
            except OpenAISearchProviderError:
                raise
            except requests.RequestException as exc:
                last_err = exc
                continue

        raise OpenAISearchProviderError(str(last_err) if last_err else "OpenAI sem resposta.")


def _extract_output_text(data: dict) -> str:
    """Extrai o texto final de uma resposta da Responses API."""
    # Conveniencia (quando presente)
    text = data.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    parts: list[str] = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"}:
                value = content.get("text") or ""
                if value:
                    parts.append(value)
    return "\n".join(parts).strip()


def _extract_grounded_output(data: dict) -> dict[str, Any]:
    """Extract text and the native URL citations attached to that text."""
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            for annotation in content.get("annotations") or []:
                if not isinstance(annotation, dict):
                    continue
                nested = annotation.get("url_citation")
                citation = nested if isinstance(nested, dict) else annotation
                if annotation.get("type") != "url_citation" and not isinstance(nested, dict):
                    continue
                url = str(citation.get("url") or "").strip()
                title = str(citation.get("title") or "").strip()
                if not url:
                    continue
                key = (url, title)
                if key in seen:
                    continue
                seen.add(key)
                citations.append(
                    {
                        "url": url,
                        "title": title,
                        "start_index": citation.get("start_index"),
                        "end_index": citation.get("end_index"),
                    }
                )

    return {
        "text": _extract_output_text(data),
        "citations": citations,
    }
