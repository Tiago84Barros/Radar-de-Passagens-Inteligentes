"""Disponibilidade da passagem rastreada entre verificações.

Resolve a dúvida "a passagem deixou de existir ou nunca existiu": a cada
verificação, se não há tarifa melhor, o bot reconfere a passagem avisada e
reporta o status no Telegram.
"""
from datetime import date

import pytest

import app.alerts as alerts
from app.db import MonitoredSearch
from services import monitoring_bot


@pytest.fixture
def captured(monkeypatch):
    """Captura as mensagens enviadas ao Telegram (sem rede)."""
    messages: list[str] = []

    def fake_send(message: str):
        messages.append(message)
        return True, "ok"

    monkeypatch.setattr(alerts, "send_telegram_message", fake_send)
    return messages


def _offer(price: float, *, airline="G3"):
    return {
        "provider": "openai_web_search",
        "source": "openai_web_search",
        "origin": "BEL",
        "destination": "FOR",
        "departure_date": "2026-07-01",
        "return_date": "2026-07-06",
        "airline": airline,
        "price": float(price),
        "currency": "BRL",
        "duration_minutes": 120,
        "stops": 0,
        "booking_link": "https://voegol.com.br",
    }


def _search():
    return MonitoredSearch(
        origin_iata="BEL",
        destination_iata="FOR",
        departure_date=date(2026, 7, 1),
        return_date=date(2026, 7, 6),
        adults=1,
        max_price=500.0,
        min_mile_value=0.035,
        consider_miles=True,
        telegram_enabled=True,
    )


def _run(monkeypatch, search, offers):
    monkeypatch.setattr(monitoring_bot, "search_all_providers", lambda params: list(offers))
    return monitoring_bot.execute_monitored_search(None, search)


def test_availability_lifecycle(monkeypatch, captured):
    search = _search()

    # 1) Tarifa barata aparece → alerta normal de "busca rastreada".
    _run(monkeypatch, search, [_offer(300.0)])
    assert "busca rastreada" in captured[-1]
    assert search.last_availability_state == "available"
    assert search.last_best_price == 300.0
    assert search.last_notification_at is not None

    # 2) Mesma passagem ainda no ar (sem nada melhor) → "ainda disponível".
    res = _run(monkeypatch, search, [_offer(300.0)])
    assert "Passagem ainda disponível" in captured[-1]
    assert res["availability_sent"] is True
    assert res["notified"] is False

    # 3) Oscila alguns reais, dentro da tolerância → ainda "disponível".
    _run(monkeypatch, search, [_offer(312.0)])
    assert "Passagem ainda disponível" in captured[-1]

    # 4) Some (preço sobe muito acima do rastreado) → avisa UMA vez.
    n_before = len(captured)
    _run(monkeypatch, search, [_offer(480.0)])
    assert "não está mais disponível" in captured[-1]
    assert len(captured) == n_before + 1
    assert search.last_availability_state == "unavailable"
    # Rastreio reancorado para permitir um novo alerta na próxima oportunidade.
    assert search.last_notification_at is None


def test_unavailable_is_announced_only_once(monkeypatch, captured):
    search = _search()

    # Estabelece uma passagem rastreada.
    _run(monkeypatch, search, [_offer(300.0)])
    assert "busca rastreada" in captured[-1]

    # Sem ofertas nenhuma → "não está mais disponível" (1ª vez).
    _run(monkeypatch, search, [])
    assert "não está mais disponível" in captured[-1]
    count_after_first = len(captured)

    # Continua sem ofertas → NÃO repete o aviso.
    _run(monkeypatch, search, [])
    assert len(captured) == count_after_first


def test_better_fare_sends_new_alert_not_availability(monkeypatch, captured):
    search = _search()

    _run(monkeypatch, search, [_offer(300.0)])
    assert "busca rastreada" in captured[-1]

    # Aparece algo MAIS BARATO → novo alerta de tarifa, não "ainda disponível".
    res = _run(monkeypatch, search, [_offer(250.0)])
    assert "busca rastreada" in captured[-1]
    assert "Passagem ainda disponível" not in captured[-1]
    assert res["notified"] is True
    assert search.last_best_price == 250.0
