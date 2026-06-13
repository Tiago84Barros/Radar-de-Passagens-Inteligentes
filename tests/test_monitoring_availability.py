"""Confirmação anti-alucinação + disponibilidade da passagem rastreada.

Duas garantias verificadas aqui:

1. Confirmação: uma tarifa nova só vira alerta quando reaparece numa SEGUNDA
   verificação seguida — corta o "preço fantasma" que some quando você vai
   olhar de manhã.
2. Disponibilidade: depois de avisada, a cada verificação o bot reconfere a
   passagem e diz se ela "ainda está disponível" ou "não está mais disponível".
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


def _establish_alert(monkeypatch, search, price=300.0):
    """Roda duas verificações com a mesma tarifa para confirmar e disparar o
    primeiro alerta (estado inicial de 'rastreando uma passagem')."""
    _run(monkeypatch, search, [_offer(price)])  # 1ª aparição → arma candidata
    return _run(monkeypatch, search, [_offer(price)])  # 2ª → confirma e alerta


# ── Confirmação ───────────────────────────────────────────────────────────────

def test_first_sighting_does_not_alert(monkeypatch, captured):
    search = _search()
    res = _run(monkeypatch, search, [_offer(300.0)])
    assert res["notified"] is False
    assert captured == []  # nada enviado ainda
    assert search.pending_alert_price == 300.0  # candidata armada


def test_second_sighting_confirms_and_alerts(monkeypatch, captured):
    search = _search()
    _run(monkeypatch, search, [_offer(300.0)])
    res = _run(monkeypatch, search, [_offer(300.0)])
    assert res["notified"] is True
    assert "busca rastreada" in captured[-1]
    assert search.last_notification_at is not None
    assert search.pending_alert_price is None  # pendência encerrada


def test_phantom_fare_seen_once_is_never_alerted(monkeypatch, captured):
    search = _search()
    _run(monkeypatch, search, [_offer(199.0)])  # tarifa fantasma aparece 1x
    _run(monkeypatch, search, [])               # some na verificação seguinte
    assert captured == []                        # nunca foi avisada
    assert search.pending_alert_price is None    # candidata descartada


# ── Disponibilidade (após confirmação) ────────────────────────────────────────

def test_availability_lifecycle(monkeypatch, captured):
    search = _search()
    _establish_alert(monkeypatch, search, 300.0)
    assert "busca rastreada" in captured[-1]
    assert search.last_availability_state == "available"
    assert search.last_best_price == 300.0

    # Mesma passagem ainda no ar (sem nada melhor) → "ainda disponível".
    res = _run(monkeypatch, search, [_offer(300.0)])
    assert "Passagem ainda disponível" in captured[-1]
    assert res["availability_sent"] is True
    assert res["notified"] is False

    # Oscila alguns reais, dentro da tolerância → ainda "disponível".
    _run(monkeypatch, search, [_offer(312.0)])
    assert "Passagem ainda disponível" in captured[-1]

    # Some (preço sobe muito acima do rastreado) → avisa UMA vez.
    n_before = len(captured)
    _run(monkeypatch, search, [_offer(480.0)])
    assert "não está mais disponível" in captured[-1]
    assert len(captured) == n_before + 1
    assert search.last_availability_state == "unavailable"
    assert search.last_notification_at is None  # rastreio reancorado


def test_unavailable_is_announced_only_once(monkeypatch, captured):
    search = _search()
    _establish_alert(monkeypatch, search, 300.0)

    _run(monkeypatch, search, [])  # sem ofertas → "não está mais disponível"
    assert "não está mais disponível" in captured[-1]
    count_after_first = len(captured)

    _run(monkeypatch, search, [])  # continua sem ofertas → NÃO repete
    assert len(captured) == count_after_first


def test_better_fare_also_requires_confirmation(monkeypatch, captured):
    search = _search()
    _establish_alert(monkeypatch, search, 300.0)
    n_before = len(captured)

    # Tarifa mais barata aparece 1x → confirma antes de avisar (não alerta já).
    res = _run(monkeypatch, search, [_offer(250.0)])
    assert res["notified"] is False
    assert search.pending_alert_price == 250.0

    # Reaparece → agora sim dispara o novo alerta de tarifa melhor.
    res = _run(monkeypatch, search, [_offer(250.0)])
    assert res["notified"] is True
    assert "busca rastreada" in captured[-1]
    assert search.last_best_price == 250.0
    assert len(captured) > n_before
