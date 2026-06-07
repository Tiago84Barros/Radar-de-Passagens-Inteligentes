"""Claude + web_search provider — busca passagens via pesquisa web em tempo real.

Substitui a dependencia de scraping (bloqueado por anti-bot) e de APIs pagas de voo:
o Claude usa a tool `web_search` (server-side, ~US$ 10 por 1000 buscas) para
pesquisar tarifas reais e responde em JSON estruturado, que validamos com Pydantic
antes de normalizar para o formato comum dos providers.

Versao da tool confirmada em docs.anthropic.com/.../web-search-tool: `web_search_20250305`
(estavel, sem exigir a tool de code execution; suficiente para este caso de uso).
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.settings import get_settings
from providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

WEB_SEARCH_TOOL_VERSION = "web_search_20250305"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_USES = 5

SYSTEM_PROMPT = (
    "Voce e um assistente de pesquisa de passagens aereas. Use a ferramenta de "
    "busca web para encontrar tarifas reais e atuais para os criterios informados. "
    "Responda SOMENTE com um array JSON (sem markdown, sem cercas ```, sem texto "
    "fora do JSON), onde cada item segue exatamente este formato:\n"
    '[{"companhia": "string", "origem": "IATA", "destino": "IATA", '
    '"data_ida": "YYYY-MM-DD", "data_volta": "YYYY-MM-DD ou null", '
    '"escalas": 0, "preco_brl": 1234.56, "link": "https://...", '
    '"fonte": "nome do site pesquisado"}]\n'
    "Se nao encontrar nenhuma tarifa real, responda com um array vazio: []."
)


class ClaudeFlightResult(BaseModel):
    """Schema esperado de cada item retornado pelo Claude (JSON da pesquisa)."""

    companhia: str = ""
    origem: str
    destino: str
    data_ida: str
    data_volta: str | None = None
    escalas: int | None = None
    preco_brl: float = Field(gt=0)
    link: str = ""
    fonte: str = ""


class ClaudeSearchProviderError(RuntimeError):
    pass


class ClaudeSearchProvider(BaseProvider):
    name = "claude_web_search"

    def __init__(self, max_uses: int = DEFAULT_MAX_USES, model: str = DEFAULT_MODEL) -> None:
        self.settings = get_settings()
        self.max_uses = max_uses
        self.model = model

    def is_configured(self) -> bool:
        return bool(getattr(self.settings, "anthropic_api_key", None))

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        currency: str = "BRL",
        adults: int = 1,
        cabin: str = "Economy",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        o = origin.upper()
        d = destination.upper()
        dep = _date_to_day(departure_date)
        ret = _date_to_day(return_date) if return_date else None

        prompt = _build_user_prompt(o, d, dep, ret, adults=adults, cabin=cabin)

        try:
            payload = self._call_claude(prompt)
        except ClaudeSearchProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - nunca derrubar o pipeline por falha externa
            logger.warning("Falha ao consultar Claude web_search: %s", exc)
            return []

        return self.normalize_response(
            payload,
            origin=o,
            destination=d,
            departure_date=dep,
            return_date=ret,
            currency=currency.upper(),
            limit=limit,
        )

    def _call_claude(self, prompt: str) -> str:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise ClaudeSearchProviderError("SDK 'anthropic' nao instalado.") from exc

        client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "type": WEB_SEARCH_TOOL_VERSION,
                    "name": "web_search",
                    "max_uses": self.max_uses,
                }
            ],
        )
        return _extract_text(message)

    def normalize_response(self, payload: Any, **kwargs: Any) -> list[dict[str, Any]]:
        items = _parse_json_array(payload)
        if items is None:
            return []

        results: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            try:
                flight = ClaudeFlightResult.model_validate(raw)
            except ValidationError as exc:
                logger.info("Item descartado (schema invalido): %s", exc)
                continue

            results.append(
                {
                    "provider": self.name,
                    "source": flight.fonte or self.name,
                    "origin": flight.origem.upper() or kwargs.get("origin"),
                    "destination": flight.destino.upper() or kwargs.get("destination"),
                    "departure_date": flight.data_ida or kwargs.get("departure_date"),
                    "return_date": flight.data_volta or kwargs.get("return_date"),
                    "airline": flight.companhia,
                    "price": float(flight.preco_brl),
                    "currency": kwargs.get("currency", "BRL"),
                    "duration_minutes": None,
                    "stops": flight.escalas,
                    "booking_link": flight.link,
                    "raw_payload": {"claude_web_search": True, "fonte": flight.fonte},
                }
            )

        results.sort(key=lambda r: r["price"])
        return results[: kwargs.get("limit", 20)]


def _build_user_prompt(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    *,
    adults: int,
    cabin: str,
) -> str:
    trecho = f"{origin} -> {destination}, ida em {departure_date}"
    if return_date:
        trecho += f", volta em {return_date}"
    return (
        f"Pesquise passagens aereas reais para o trecho {trecho}, "
        f"{adults} passageiro(s), classe {cabin}, com preco em reais (BRL). "
        "Retorne apenas o array JSON especificado, com as melhores opcoes encontradas."
    )


def _extract_text(message: Any) -> str:
    """Concatena os blocos de texto da resposta (ignora server_tool_use etc.)."""
    parts: list[str] = []
    for block in getattr(message, "content", None) or []:
        block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if block_type == "text":
            text = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
            if text:
                parts.append(text)
    return "\n".join(parts)


def _parse_json_array(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, str):
        return None

    text = payload.strip()
    if text.startswith("```"):
        text = text.strip("`")
        # remove possivel marcador de linguagem (ex.: "json\n...")
        if "\n" in text:
            first_line, rest = text.split("\n", 1)
            if first_line.strip().lower() in {"json", ""}:
                text = rest
        text = text.strip()

    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        logger.info("Resposta do Claude nao e JSON valido: %s", exc)
        return None

    if not isinstance(data, list):
        logger.info("Resposta do Claude nao e um array JSON: %r", type(data))
        return None
    return data


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]
