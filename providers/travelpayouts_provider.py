from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import requests

from app.settings import get_settings
from providers.base_provider import BaseProvider


class TravelPayoutsProvider(BaseProvider):
    name = "travelpayouts"
    BASE_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"

    def __init__(self, timeout: int = 20) -> None:
        self.settings = get_settings()
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.settings.travelpayouts_api_token)

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        currency: str = "brl",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        # 1) Tenta a data exata pedida pelo usuario primeiro. Pedir o mes
        # inteiro de cara mascara o problema: o usuario busca um dia preciso
        # e recebe "o mais barato em qualquer dia do mes" exibido como se
        # fosse o resultado da busca dele — o que parece "informacao errada".
        exact_results = self._fetch(
            origin=origin,
            destination=destination,
            departure_at=_date_to_day(departure_date),
            return_at=_date_to_day(return_date) if return_date else None,
            return_date=return_date,
            currency=currency,
            limit=limit,
        )
        if exact_results:
            for item in exact_results:
                item["date_match"] = "exact"
            return exact_results

        # 2) Sem cache para o dia exato: amplia para o mes inteiro como
        # segunda tentativa (maximiza a chance de trazer alguma cotacao real),
        # mas marca claramente que a data exibida e "melhor achado no mes" e
        # nao a data pedida — a UI/IA de decisao precisa avisar o usuario.
        month_results = self._fetch(
            origin=origin,
            destination=destination,
            departure_at=_date_to_month(departure_date),
            return_at=_date_to_month(return_date) if return_date else None,
            return_date=return_date,
            currency=currency,
            limit=limit,
        )
        for item in month_results:
            item["date_match"] = "month_fallback"
            item["requested_date"] = _date_to_day(departure_date)
        return month_results

    def search_flexible_dates(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        flex_days: int = 0,
        currency: str = "brl",
        limit_per_day: int = 10,
    ) -> list[dict[str, Any]]:
        """Varre os dias vizinhos a data pedida (departure_date +/- flex_days,
        uma chamada por dia) e devolve as cotacoes reais encontradas em cada
        um. Controlado pelo usuario (slider de "tolerancia de datas"): preco
        de passagem varia bastante de um dia para o outro, entao alargar a
        janela de busca aumenta a chance de achar uma tarifa bem mais barata
        perto da data desejada. Cada item vem marcado com 'date_match' =
        'flex_search', 'date_offset_days' e 'requested_date' para a UI deixar
        claro que a data encontrada e diferente da pedida — nunca disfarçar."""
        if not self.is_configured() or flex_days <= 0:
            return []

        base_departure = _to_date(departure_date)
        base_return = _to_date(return_date) if return_date else None
        requested = _date_to_day(departure_date)

        results: list[dict[str, Any]] = []
        for offset in range(-flex_days, flex_days + 1):
            if offset == 0:
                continue  # dia exato ja coberto por search_flights
            day = base_departure + timedelta(days=offset)
            if day < date.today():
                continue
            return_day = (base_return + timedelta(days=offset)) if base_return else None
            try:
                day_results = self._fetch(
                    origin=origin,
                    destination=destination,
                    departure_at=_date_to_day(day),
                    return_at=_date_to_day(return_day) if return_day else None,
                    return_date=return_date,
                    currency=currency,
                    limit=limit_per_day,
                )
            except TravelPayoutsProviderError:
                continue
            for item in day_results:
                item["date_match"] = "flex_search"
                item["date_offset_days"] = offset
                item["requested_date"] = requested
            results.extend(day_results)
        return results

    def _fetch(
        self,
        *,
        origin: str,
        destination: str,
        departure_at: str,
        return_at: str | None,
        return_date: date | str | None,
        currency: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        params = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_at": departure_at,
            "currency": currency.lower(),
            "limit": limit,
            "page": 1,
            "token": self.settings.travelpayouts_api_token,
            "sorting": "price",
            "one_way": "false" if return_date else "true",
        }
        if return_at:
            params["return_at"] = return_at

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=self.timeout)
            if response.status_code in {401, 403}:
                raise TravelPayoutsProviderError(
                    "Token da Travelpayouts recusado. Confira se o secret TRAVELPAYOUTS_API_TOKEN esta correto.",
                    status_code=response.status_code,
                )
            response.raise_for_status()
            payload = response.json()
        except TravelPayoutsProviderError:
            raise
        except requests.RequestException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise TravelPayoutsProviderError(
                "Nao foi possivel consultar a Travelpayouts agora. Tente novamente em alguns minutos.",
                status_code=status_code,
            ) from exc
        except ValueError as exc:
            raise TravelPayoutsProviderError("A Travelpayouts retornou uma resposta invalida.") from exc

        if isinstance(payload, dict) and payload.get("success") is False:
            error = payload.get("error") or payload.get("errors") or "resposta sem sucesso"
            raise TravelPayoutsProviderError(f"A Travelpayouts recusou a consulta: {_safe_error_text(error)}")

        return self.normalize_response(
            payload,
            origin=origin,
            destination=destination,
            departure_date=departure_at,
            return_date=return_date,
            currency=currency,
        )

    def search_year_flights(
        self,
        origin: str,
        destination: str,
        start_date: date | str,
        return_date: date | str | None = None,
        currency: str = "brl",
        limit_per_month: int = 100,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        start_month = _month_start(start_date)
        for offset in range(12):
            month = _add_months(start_month, offset)
            month_results = self.search_flights(
                origin=origin,
                destination=destination,
                departure_date=month,
                return_date=return_date,
                currency=currency,
                limit=limit_per_month,
            )
            for item in month_results:
                item["raw_payload"] = {
                    **dict(item.get("raw_payload") or {}),
                    "calendar_collection": "year",
                    "calendar_month": _date_to_month(month),
                }
            results.extend(month_results)
        return results

    def normalize_response(self, payload: Any, **kwargs: Any) -> list[dict[str, Any]]:
        data = payload.get("data", []) if isinstance(payload, dict) else []
        results: list[dict[str, Any]] = []
        for item in data:
            price = item.get("price")
            if price is None:
                continue
            departure_at = item.get("departure_at") or kwargs["departure_date"]
            return_at = item.get("return_at") or kwargs.get("return_date")
            link = item.get("link") or ""
            results.append(
                {
                    "provider": self.name,
                    "source": self.name,
                    "origin": (item.get("origin") or kwargs["origin"]).upper(),
                    "destination": (item.get("destination") or kwargs["destination"]).upper(),
                    "departure_date": _date_to_day(departure_at),
                    "departure_at": str(departure_at),
                    "return_date": _date_to_day(return_at) if return_at else None,
                    "return_at": str(return_at) if return_at else None,
                    "airline": item.get("airline") or "",
                    "flight_number": item.get("flight_number") or "",
                    "price": float(price),
                    "currency": str(item.get("currency") or kwargs.get("currency") or "BRL").upper(),
                    "duration_minutes": item.get("duration"),
                    "stops": item.get("transfers"),
                    "booking_link": f"https://www.aviasales.com{link}" if link.startswith("/") else link,
                    "raw_payload": item,
                }
            )
        return results


class TravelPayoutsProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _safe_error_text(value: Any) -> str:
    text = str(value)
    token = get_settings().travelpayouts_api_token or ""
    if token:
        text = text.replace(token, "[token oculto]")
    return text[:240]


def _date_to_month(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:7]


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]


def _to_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(_date_to_day(value))


def _month_start(value: date | str) -> date:
    text = _date_to_day(value)
    year, month, _ = text.split("-")
    return date(int(year), int(month), 1)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)
