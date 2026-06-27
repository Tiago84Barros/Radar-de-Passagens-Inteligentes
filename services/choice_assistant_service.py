"""Grounded choice assistant for confirmed flight offers.

The LLM never returns prices, dates, links, airlines, or free-form claims. It
may only select an existing offer ID and reason/warning codes that the
application has already computed from structured API data. All user-facing
facts are rendered locally from the selected offer.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, Field, ValidationError

from app.settings import Settings, get_settings
from services.recommendation_service import rank_flight_options

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_TIMEOUT_SECONDS = 45
MAX_OFFERS_FOR_AI = 12

ENGINE_AUTO = "auto"
ENGINE_LOCAL = "local"
ENGINE_OPENAI = "openai"
ENGINE_GEMINI = "gemini"

REAL_SOURCE_MARKERS = (
    "serpapi",
    "google_flights",
    "travelpayouts",
    "combinado",
    "montado_ida_volta",
)

REASON_LABELS = {
    "LOWEST_PRICE": "É a opção confirmada de menor preço.",
    "FASTEST": "Tem a menor duração entre as opções confirmadas.",
    "FEWEST_STOPS": "Tem o menor número de conexões encontrado.",
    "DIRECT_FLIGHT": "É um voo direto.",
    "WITHIN_BUDGET": "Está dentro do orçamento informado.",
    "GOOD_TIME_VALUE": "Economiza bastante tempo com acréscimo de preço moderado.",
    "BALANCED": "Apresenta o melhor equilíbrio calculado entre preço, duração e conexões.",
    "VERIFIED_MILES": "Possui uma oferta em milhas informada pela fonte, não apenas estimada.",
    "SINGLE_BOOKING": "Mantém ida e volta na mesma reserva, com proteção conjunta.",
}

WARNING_LABELS = {
    "OVER_BUDGET": "O preço ultrapassa o orçamento informado.",
    "SEPARATE_TICKETS": "A viagem exige bilhetes separados, sem proteção conjunta.",
    "AIRLINE_CHANGE": "Há troca de companhia aérea no itinerário.",
    "HIGH_CONNECTION_RISK": "A conexão foi classificada como de alto risco.",
    "MULTIPLE_STOPS": "O itinerário possui duas ou mais conexões.",
    "LONGER_THAN_FASTEST": "Há uma alternativa confirmada consideravelmente mais rápida.",
    "MILES_ESTIMATE_ONLY": "As milhas exibidas são apenas uma estimativa; não há emissão confirmada.",
    "NO_DIRECT_LINK": "A API não forneceu um link direto para esta tarifa.",
}

REASON_PRIORITY = (
    "BALANCED",
    "SINGLE_BOOKING",
    "LOWEST_PRICE",
    "FASTEST",
    "DIRECT_FLIGHT",
    "WITHIN_BUDGET",
    "GOOD_TIME_VALUE",
    "FEWEST_STOPS",
    "VERIFIED_MILES",
)

WARNING_PRIORITY = (
    "OVER_BUDGET",
    "SEPARATE_TICKETS",
    "HIGH_CONNECTION_RISK",
    "AIRLINE_CHANGE",
    "MULTIPLE_STOPS",
    "LONGER_THAN_FASTEST",
    "MILES_ESTIMATE_ONLY",
    "NO_DIRECT_LINK",
)

SYSTEM_INSTRUCTIONS = (
    "Voce e um assistente de decisao para passagens aereas. Os dados recebidos "
    "ja foram confirmados por APIs e sao o unico universo permitido. Nao use "
    "conhecimento externo, nao pesquise a web e nao crie fatos. Escolha somente "
    "um offer_id existente. Use apenas reason_codes e warning_codes listados "
    "como validos para a oferta escolhida. Responda somente com JSON no formato "
    '{"selected_offer_id":"F1","reason_codes":["BALANCED"],'
    '"warning_codes":[],"alternative_offer_id":null}. '
    "Nao inclua texto, precos, datas, links ou nomes na resposta."
)


class AIChoice(BaseModel):
    selected_offer_id: str
    reason_codes: list[str] = Field(default_factory=list, max_length=4)
    warning_codes: list[str] = Field(default_factory=list, max_length=4)
    alternative_offer_id: str | None = None


def assistant_engines(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    engines = [ENGINE_LOCAL]
    if settings.openai_api_key:
        engines.append(ENGINE_OPENAI)
    if settings.gemini_api_key:
        engines.append(ENGINE_GEMINI)
    return engines


def is_confirmed_offer(option: dict[str, Any]) -> bool:
    """Accept only linked structured-API or explicitly verified offers."""
    confidence = str(option.get("source_confidence") or "").strip().lower()
    source = " ".join(
        str(option.get(field) or "").strip().lower()
        for field in ("provider", "source")
    )
    has_link = any(
        _valid_http_url(option.get(field))
        for field in ("booking_link", "source_url", "outbound_booking_link", "return_booking_link")
    )
    try:
        has_price = float(option.get("price_brl") or option.get("price") or 0) > 0
    except (TypeError, ValueError):
        has_price = False

    if not has_price or not has_link:
        return False
    if confidence == "verified":
        return True
    return confidence == "real" and any(marker in source for marker in REAL_SOURCE_MARKERS)


def analyze_confirmed_offers(
    offers: list[dict[str, Any]],
    preferences: dict[str, Any] | None = None,
    *,
    engine: str = ENGINE_AUTO,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Select and explain the best confirmed offer without trusting LLM facts."""
    settings = settings or get_settings()
    preferences = preferences or {}
    confirmed_count = sum(1 for offer in offers if is_confirmed_offer(offer))
    prepared = _prepare_offers(offers, preferences)
    if not prepared:
        return {
            "ok": False,
            "mode": ENGINE_LOCAL,
            "message": "Não há tarifas confirmadas e vinculadas a uma fonte para analisar.",
        }

    requested_engine = _resolve_engine(engine, settings)
    selection: AIChoice | None = None
    fallback_reason: str | None = None

    if requested_engine in {ENGINE_OPENAI, ENGINE_GEMINI}:
        try:
            raw = (
                _call_openai(prepared, preferences, settings)
                if requested_engine == ENGINE_OPENAI
                else _call_gemini(prepared, preferences, settings)
            )
            selection = _validate_ai_choice(raw, prepared)
            if selection is None:
                fallback_reason = "A IA respondeu fora do contrato seguro; foi aplicada a análise local."
        except Exception:  # noqa: BLE001 - failure must never break the results screen
            fallback_reason = "A IA não respondeu agora; foi aplicada a análise local."

    if selection is None:
        selection = _local_choice(prepared, preferences)
        mode = ENGINE_LOCAL
    else:
        mode = requested_engine

    selected = _offer_by_id(prepared, selection.selected_offer_id) or prepared[0]
    valid_reasons = set(selected["_valid_reason_codes"])
    valid_warnings = set(selected["_valid_warning_codes"])
    reason_codes = [code for code in selection.reason_codes if code in valid_reasons][:4]
    warning_codes = [code for code in selection.warning_codes if code in valid_warnings][:4]
    if not reason_codes:
        reason_codes = _ordered_codes(valid_reasons, REASON_PRIORITY, limit=3)

    cheapest = min(prepared, key=_price)
    alternative = cheapest if cheapest is not selected else None
    best_closed = _best_group_option(
        [item for item in prepared if not _is_separate_round_trip(item)],
        preferences,
    )
    best_separate = _best_group_option(
        [item for item in prepared if _is_separate_round_trip(item)],
        preferences,
    )

    return {
        "ok": True,
        "mode": mode,
        "engine_label": {
            ENGINE_OPENAI: "OpenAI",
            ENGINE_GEMINI: "Gemini",
            ENGINE_LOCAL: "Análise local segura",
        }[mode],
        "selected_offer": _public_offer(selected),
        "verdict_kind": _purchase_type(selected),
        "reasons": [REASON_LABELS[code] for code in reason_codes],
        "warnings": [WARNING_LABELS[code] for code in warning_codes],
        "alternative_offer": _public_offer(alternative) if alternative else None,
        "best_closed_offer": _public_offer(best_closed),
        "best_separate_offer": _public_offer(best_separate),
        "fallback_reason": fallback_reason,
        "confirmed_count": confirmed_count,
    }


def _prepare_offers(offers: list[dict[str, Any]], preferences: dict[str, Any]) -> list[dict[str, Any]]:
    confirmed = [dict(option) for option in offers if is_confirmed_offer(option)]
    if not confirmed:
        return []

    ranking = rank_flight_options(confirmed, {**preferences, "sort_by": "recomendados"})
    ranked = list(ranking["sorted_options"])
    # Preserve the best candidate from each booking format even when one group
    # dominates the first page, plus the global cheapest and fastest options.
    representatives = [
        _best_group_option(
            [item for item in confirmed if not _is_separate_round_trip(item)],
            preferences,
        ),
        _best_group_option(
            [item for item in confirmed if _is_separate_round_trip(item)],
            preferences,
        ),
        ranking.get("cheapest_option"),
        ranking.get("fastest_option"),
    ]
    ordered: list[dict[str, Any]] = []
    for candidate in [*representatives, *ranked]:
        if candidate is not None and candidate not in ordered:
            ordered.append(candidate)
        if len(ordered) >= MAX_OFFERS_FOR_AI:
            break
    cheapest_price = min(_price(option) for option in ordered)
    fastest_duration = min(
        (_duration(option) for option in ordered if _duration(option) > 0),
        default=0,
    )
    fewest_stops = min(_stops(option) for option in ordered)
    recommended = ranking.get("recommended_option")

    prepared: list[dict[str, Any]] = []
    for index, option in enumerate(ordered, start=1):
        item = dict(option)
        item["_offer_id"] = f"F{index}"
        item["_valid_reason_codes"] = _reason_codes(
            item,
            is_recommended=option is recommended,
            cheapest_price=cheapest_price,
            fastest_duration=fastest_duration,
            fewest_stops=fewest_stops,
            preferences=preferences,
        )
        item["_valid_warning_codes"] = _warning_codes(
            item,
            fastest_duration=fastest_duration,
            preferences=preferences,
        )
        prepared.append(item)
    return prepared


def _reason_codes(
    option: dict[str, Any],
    *,
    is_recommended: bool,
    cheapest_price: float,
    fastest_duration: int,
    fewest_stops: int,
    preferences: dict[str, Any],
) -> list[str]:
    codes: set[str] = set()
    price = _price(option)
    duration = _duration(option)
    stops = _stops(option)
    max_price = _optional_float(preferences.get("max_price"))

    if abs(price - cheapest_price) < 0.01:
        codes.add("LOWEST_PRICE")
    if fastest_duration and duration == fastest_duration:
        codes.add("FASTEST")
    if stops == fewest_stops:
        codes.add("FEWEST_STOPS")
    if stops == 0:
        codes.add("DIRECT_FLIGHT")
    if max_price and price <= max_price:
        codes.add("WITHIN_BUDGET")
    if is_recommended:
        codes.add("BALANCED")
    if option.get("miles_offer") and (option["miles_offer"] or {}).get("amount"):
        codes.add("VERIFIED_MILES")
    if option.get("return_date") and not _is_separate_round_trip(option):
        codes.add("SINGLE_BOOKING")
    return _ordered_codes(codes, REASON_PRIORITY)


def _warning_codes(
    option: dict[str, Any],
    *,
    fastest_duration: int,
    preferences: dict[str, Any],
) -> list[str]:
    codes: set[str] = set()
    max_price = _optional_float(preferences.get("max_price"))
    if max_price and _price(option) > max_price:
        codes.add("OVER_BUDGET")
    if option.get("separate_ticket") or option.get("separate_round_trip"):
        codes.add("SEPARATE_TICKETS")
    if option.get("airline_change"):
        codes.add("AIRLINE_CHANGE")
    if str(option.get("connection_risk") or "").lower() == "alto":
        codes.add("HIGH_CONNECTION_RISK")
    if _stops(option) >= 2:
        codes.add("MULTIPLE_STOPS")
    if fastest_duration and _duration(option) >= fastest_duration + 180:
        codes.add("LONGER_THAN_FASTEST")
    if preferences.get("consider_miles", True) and not (option.get("miles_offer") or {}).get("amount"):
        codes.add("MILES_ESTIMATE_ONLY")
    if not _valid_http_url(option.get("booking_link")):
        codes.add("NO_DIRECT_LINK")
    return _ordered_codes(codes, WARNING_PRIORITY)


def _local_choice(prepared: list[dict[str, Any]], preferences: dict[str, Any]) -> AIChoice:
    ranking = rank_flight_options(prepared, {**preferences, "sort_by": "recomendados"})
    selected = ranking.get("recommended_option") or prepared[0]
    reasons = list(selected["_valid_reason_codes"])[:3]
    warnings = list(selected["_valid_warning_codes"])[:3]

    cheapest = ranking.get("cheapest_option")
    alternative_id = None
    if cheapest is not None and cheapest is not selected:
        alternative_id = cheapest["_offer_id"]
    return AIChoice(
        selected_offer_id=selected["_offer_id"],
        reason_codes=reasons,
        warning_codes=warnings,
        alternative_offer_id=alternative_id,
    )


def _resolve_engine(engine: str, settings: Settings) -> str:
    normalized = str(engine or ENGINE_AUTO).strip().lower()
    if normalized == ENGINE_OPENAI and settings.openai_api_key:
        return ENGINE_OPENAI
    if normalized == ENGINE_GEMINI and settings.gemini_api_key:
        return ENGINE_GEMINI
    if normalized == ENGINE_LOCAL:
        return ENGINE_LOCAL
    preferred = str(getattr(settings, "choice_assistant_provider", ENGINE_AUTO) or ENGINE_AUTO).lower()
    if preferred == ENGINE_OPENAI and settings.openai_api_key:
        return ENGINE_OPENAI
    if preferred == ENGINE_GEMINI and settings.gemini_api_key:
        return ENGINE_GEMINI
    if settings.openai_api_key:
        return ENGINE_OPENAI
    if settings.gemini_api_key:
        return ENGINE_GEMINI
    return ENGINE_LOCAL


def _call_openai(
    prepared: list[dict[str, Any]], preferences: dict[str, Any], settings: Settings
) -> str:
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openai_choice_model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": json.dumps(_ai_payload(prepared, preferences), ensure_ascii=False),
            "temperature": 0,
        },
        timeout=OPENAI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _extract_openai_text(response.json())


def _call_gemini(
    prepared: list[dict[str, Any]], preferences: dict[str, Any], settings: Settings
) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_choice_model,
        contents=json.dumps(_ai_payload(prepared, preferences), ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTIONS,
            response_mime_type="application/json",
            temperature=0,
        ),
    )
    return str(response.text or "")


def _ai_payload(prepared: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any]:
    return {
        "preferences": {
            "max_price": _optional_float(preferences.get("max_price")),
            "max_stops": preferences.get("max_stops"),
            "max_duration_minutes": preferences.get("max_duration_minutes"),
            "consider_miles": bool(preferences.get("consider_miles", True)),
        },
        "offers": [
            {
                "offer_id": item["_offer_id"],
                "price_brl": _price(item),
                "duration_minutes": _duration(item),
                "stops": _stops(item),
                "has_verified_miles": bool((item.get("miles_offer") or {}).get("amount")),
                "purchase_type": _purchase_type(item),
                "valid_reason_codes": item["_valid_reason_codes"],
                "valid_warning_codes": item["_valid_warning_codes"],
            }
            for item in prepared
        ],
    }


def _validate_ai_choice(raw: str, prepared: list[dict[str, Any]]) -> AIChoice | None:
    parsed = _parse_json_object(raw)
    if parsed is None:
        return None
    try:
        choice = AIChoice.model_validate(parsed)
    except ValidationError:
        return None

    selected = _offer_by_id(prepared, choice.selected_offer_id)
    if selected is None:
        return None
    valid_reasons = set(selected["_valid_reason_codes"])
    valid_warnings = set(selected["_valid_warning_codes"])
    choice.reason_codes = [code for code in choice.reason_codes if code in valid_reasons]
    choice.warning_codes = [code for code in choice.warning_codes if code in valid_warnings]
    if choice.alternative_offer_id and _offer_by_id(prepared, choice.alternative_offer_id) is None:
        choice.alternative_offer_id = None
    return choice


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _extract_openai_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks).strip()


def _public_offer(option: dict[str, Any] | None) -> dict[str, Any] | None:
    if option is None:
        return None
    return {key: value for key, value in option.items() if not key.startswith("_")}


def _offer_by_id(
    prepared: list[dict[str, Any]], offer_id: str | None
) -> dict[str, Any] | None:
    if not offer_id:
        return None
    return next((item for item in prepared if item["_offer_id"] == offer_id), None)


def _best_group_option(
    options: list[dict[str, Any]],
    preferences: dict[str, Any],
) -> dict[str, Any] | None:
    if not options:
        return None
    ranking = rank_flight_options(options, {**preferences, "sort_by": "recomendados"})
    return ranking.get("recommended_option") or ranking.get("cheapest_option")


def _is_separate_round_trip(option: dict[str, Any]) -> bool:
    return bool(option.get("separate_round_trip"))


def _purchase_type(option: dict[str, Any]) -> str:
    if not option.get("return_date"):
        return "one_way"
    return "separate_reservations" if _is_separate_round_trip(option) else "single_booking"


def _ordered_codes(codes: set[str], priority: tuple[str, ...], limit: int | None = None) -> list[str]:
    ordered = [code for code in priority if code in codes]
    return ordered[:limit] if limit else ordered


def _price(option: dict[str, Any]) -> float:
    return float(option.get("price_brl") or option.get("price") or 0)


def _duration(option: dict[str, Any] | None) -> int:
    if not option:
        return 0
    return int(option.get("duration_minutes") or 0)


def _stops(option: dict[str, Any]) -> int:
    return int(option.get("stops") or 0)


def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _valid_http_url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
