"""Confiabilidade da tarifa (corroboração sem atraso) + disponibilidade.

Duas garantias verificadas aqui:

1. Confiabilidade: o alerta sai NA HORA (não perde tarifa que some rápido), mas
   leva um selo — "confirmada" quando vem de preço real ou é corroborada por
   outra fonte na mesma busca; "a confirmar" quando é uma tarifa solitária de
   busca web (risco de preço fantasma).
2. Disponibilidade: depois de avisada, a cada verificação o bot reconfere a
   passagem e diz se "ainda está disponível" ou "não está mais disponível".
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


def _offer(price: float, *, airline="G3", provider="openai_web_search"):
    return {
        "provider": provider,
        "source": provider,
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


# ── Confiabilidade (corroboração na mesma busca, sem atraso) ───────────────────

def test_lone_web_fare_alerts_immediately_marked_unconfirmed(monkeypatch, captured):
    search = _search()
    res = _run(monkeypatch, search, [_offer(300.0, provider="openai_web_search")])
    assert res["notified"] is True                       # alerta SAIU na hora
    assert "busca rastreada" in captured[-1]
    assert "Confiabilidade: a confirmar" in captured[-1]  # mas marcado "a confirmar"


def test_real_price_source_is_marked_confirmed(monkeypatch, captured):
    search = _search()
    _run(monkeypatch, search, [_offer(300.0, provider="travelpayouts")])
    assert "Confiabilidade: confirmada" in captured[-1]


def test_corroborated_web_fare_is_marked_confirmed(monkeypatch, captured):
    search = _search()
    # Duas fontes web independentes com preço equivalente → corroborada.
    _run(monkeypatch, search, [
        _offer(300.0, provider="openai_web_search"),
        _offer(305.0, provider="gemini_web_search"),
    ])
    assert "Confiabilidade: confirmada" in captured[-1]


def test_fare_confidence_helper():
    best = _offer(300.0, provider="openai_web_search")
    # solitária
    assert monitoring_bot._fare_confidence(best, [best]) == "unconfirmed"
    # corroborada por outra fonte
    other = _offer(310.0, provider="gemini_web_search")
    assert monitoring_bot._fare_confidence(best, [best, other]) == "confirmed"
    # fonte de preço real
    real = _offer(300.0, provider="travelpayouts")
    assert monitoring_bot._fare_confidence(real, [real]) == "confirmed"


# ── Disponibilidade (após o alerta) ───────────────────────────────────────────

def test_availability_lifecycle(monkeypatch, captured):
    search = _search()
    _run(monkeypatch, search, [_offer(300.0)])  # alerta imediato
    assert "busca rastreada" in captured[-1]
    assert search.last_best_price == 300.0

    # Mesma passagem ainda no ar (sem nada melhor) → "ainda disponível".
    res = _run(monkeypatch, search, [_offer(300.0)])
    assert "Passagem ainda disponível" in captured[-1]
    assert res["availability_sent"] is True
    assert res["notified"] is False

    # Oscila dentro da tolerância → ainda "disponível".
    _run(monkeypatch, search, [_offer(312.0)])
    assert "Passagem ainda disponível" in captured[-1]

    # Some (preço sobe muito) → avisa UMA vez e reancora.
    n_before = len(captured)
    _run(monkeypatch, search, [_offer(480.0)])
    assert "não está mais disponível" in captured[-1]
    assert len(captured) == n_before + 1
    assert search.last_notification_at is None  # reancorado p/ próxima oportunidade


def test_provider_outage_does_not_claim_unavailability(monkeypatch, captured):
    search = _search()
    _run(monkeypatch, search, [_offer(300.0)])
    assert "busca rastreada" in captured[-1]
    count_before = len(captured)

    result = _run(monkeypatch, search, [])

    assert len(captured) == count_before
    assert "rastreio preservado" in result["message"]
    assert search.last_best_price == 300.0
    assert search.last_notification_at is not None


def test_different_fare_same_price_is_not_the_tracked_fare(monkeypatch, captured):
    search = _search()
    _run(monkeypatch, search, [_offer(300.0, airline="G3")])

    replacement = _offer(300.0, airline="LA")
    replacement["booking_link"] = "https://latamairlines.com"
    _run(monkeypatch, search, [replacement])

    assert "não está mais disponível" in captured[-1]


def test_demo_offer_never_sends_purchase_alert(monkeypatch, captured):
    search = _search()
    demo = _offer(100.0, provider="travelpayouts_demo")
    demo["source_confidence"] = "demo"

    result = _run(monkeypatch, search, [demo])

    assert result["notified"] is False
    assert captured == []
    assert "demonstração" in result["message"]


def test_failed_unavailability_notification_preserves_tracking(monkeypatch):
    search = _search()
    sent: list[str] = []

    def first_send(message: str):
        sent.append(message)
        return True, "ok"

    monkeypatch.setattr(alerts, "send_telegram_message", first_send)
    _run(monkeypatch, search, [_offer(300.0)])

    monkeypatch.setattr(alerts, "send_telegram_message", lambda message: (False, "telegram_send_failed"))
    other = _offer(500.0, airline="LA")
    other["booking_link"] = "https://latamairlines.com"
    result = _run(monkeypatch, search, [other])

    assert result["availability_sent"] is False
    assert search.last_best_price == 300.0
    assert search.last_notification_at is not None
    assert "falha ao avisar" in result["message"]


def test_tracking_window_follows_departure_date():
    """Rastreia até a data da viagem (não mais 24h após a criação)."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    future = _search()
    future.departure_date = (now + timedelta(days=30)).date()
    assert monitoring_bot.is_within_tracking_window(future, now) is True

    past = _search()
    past.departure_date = (now - timedelta(days=1)).date()
    assert monitoring_bot.is_within_tracking_window(past, now) is False

    # Busca criada há muito tempo, mas viagem ainda no futuro -> continua ativa
    # (o bug antigo a expirava em 24h).
    old_creation = _search()
    old_creation.created_at = now - timedelta(days=10)
    old_creation.departure_date = (now + timedelta(days=5)).date()
    assert monitoring_bot.is_within_tracking_window(old_creation, now) is True


def test_run_due_monitors_end_to_end(tmp_path, monkeypatch, captured):
    """Regressão do 'silêncio total': o run completo (carrega buscas do banco +
    processa + envia) precisa funcionar contra um banco criado pelo create_all,
    sem depender de migração de coluna nova. Cobre o caminho que quebrava quando
    o model exigia uma coluna que o banco não tinha."""
    from datetime import datetime, timedelta, timezone

    import app.db as db

    # Data de ida no futuro (relativa a agora) — o rastreio vai até a viagem.
    future_dep = (datetime.now(timezone.utc) + timedelta(days=60)).date()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'radar.db'}")
    monkeypatch.setattr(db, "_ENGINE", None)
    monkeypatch.setattr(db, "_SESSION_LOCAL", None)
    db.init_db()
    with db.session_scope() as s:
        s.add(MonitoredSearch(
            status="active", origin_iata="BEL", destination_iata="FOR",
            departure_date=future_dep, return_date=future_dep + timedelta(days=5),
            adults=1, max_price=500.0, min_mile_value=0.035, consider_miles=True,
            telegram_enabled=True, created_at=datetime.now(timezone.utc),
        ))

    monkeypatch.setattr(monitoring_bot, "search_all_providers", lambda params: [_offer(300.0)])
    result = monitoring_bot.run_due_monitors(force=True)

    assert result["alerts_sent"] == 1
    assert result["errors"] == 0
    assert any("busca rastreada" in m for m in captured)

    db.get_engine().dispose()
    monkeypatch.setattr(db, "_ENGINE", None)
    monkeypatch.setattr(db, "_SESSION_LOCAL", None)


def test_better_fare_alerts_immediately(monkeypatch, captured):
    search = _search()
    _run(monkeypatch, search, [_offer(300.0)])
    assert "busca rastreada" in captured[-1]

    # Tarifa mais barata aparece → novo alerta na hora (sem esperar ciclo).
    res = _run(monkeypatch, search, [_offer(250.0)])
    assert res["notified"] is True
    assert "busca rastreada" in captured[-1]
    assert search.last_best_price == 250.0
