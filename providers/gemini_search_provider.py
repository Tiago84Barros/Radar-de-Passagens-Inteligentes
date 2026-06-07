"""Gemini + Google Search provider — busca passagens via pesquisa web em tempo real.

Mesmo racional do ClaudeSearchProvider: evita dependencia de scraping (bloqueado
por anti-bot) e de APIs pagas de voo. O Gemini usa a ferramenta de grounding
`google_search` (server-side) para pesquisar tarifas reais e responde em JSON
estruturado, validado com Pydantic antes de normalizar para o formato comum
dos providers. Roda com a mesma chave (`GEMINI_API_KEY`) ja usada em
price_alert_bot.py — sem custo adicional de configuracao.
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

DEFAULT_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "Voce e um assistente de pesquisa de passagens aereas. Use a ferramenta de "
    "busca do Google para encontrar tarifas reais e atuais para os criterios "
    "informados. Responda SOMENTE com um array JSON (sem markdown, sem cercas "
    "```, sem texto fora do JSON), onde cada item segue exatamente este formato:\n"
    '[{"companhia": "string", "origem": "IATA", "destino": "IATA", '
    '"data_ida": "YYYY-MM-DD", "data_volta": "YYYY-MM-DD ou null", '
    '"escalas": 0, "preco_brl": 1234.56, "link": "https://...", '
    '"fonte": "nome do site pesquisado"}]\n'
    "Se nao encontrar nenhuma tarifa real, responda com um array vazio: []."
)


class GeminiFlightResult(BaseModel):
    """Schema esperado de cada item retornado pelo Gemini (JSON da pesquisa)."""

    companhia: str = ""
    origem: str
    destino: str
    data_ida: str
    data_volta: str | None = None
    escalas: int | None = None
    preco_brl: float = Field(gt=0)
    link: str = ""
    fonte: str = ""


class GeminiSearchProviderError(RuntimeError):
    pass


class GeminiSearchProvider(BaseProvider):
    name = "gemini_web_search"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.settings = get_settings()
        self.model = model

    def is_configured(self) -> bool:
        return bool(getattr(self.settings, "gemini_api_key", None))

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
            payload = self._call_gemini(prompt)
        except GeminiSearchProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - nunca derrubar o pipeline por falha externa
            logger.warning("Falha ao consultar Gemini web search: %s", exc)
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

    def _call_gemini(self, prompt: str) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover
            raise GeminiSearchProviderError("SDK 'google-genai' nao instalado.") from exc

        client = genai.Client(api_key=self.settings.gemini_api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        return (getattr(response, "text", None) or "").strip()

    def normalize_response(self, payload: Any, **kwargs: Any) -> list[dict[str, Any]]:
        items = _parse_json_array(payload)
        if items is None:
            return []

        results: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            try:
                flight = GeminiFlightResult.model_validate(raw)
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
                    "raw_payload": {"gemini_web_search": True, "fonte": flight.fonte},
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
        logger.info("Resposta do Gemini nao e JSON valido: %s", exc)
        return None

    if not isinstance(data, list):
        logger.info("Resposta do Gemini nao e um array JSON: %r", type(data))
        return None
    return data


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]
