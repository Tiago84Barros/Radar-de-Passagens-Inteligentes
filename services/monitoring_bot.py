"""The monitoring bot — runs scheduled checks for tracked searches.

Per spec, the bot does NOT feed the app's main screen with history. It only:
  1. runs each due ``monitored_searches`` row through the search providers
     (Travelpayouts = fonte de precos reais; Gemini = apoio/fallback),
  2. finds the best fare for the tracked window,
  3. sends a Telegram alert when it is worth surfacing,
  4. updates the search's status-summary fields (last_checked_at,
     last_best_price, last_best_link, last_status_message, ...).

No quote history, no price graphs, no separate run-log table — the row IS the
summary. Runs every 2h via ``.github/workflows/monitor-searches.yml`` (cron +
workflow_dispatch) through ``scripts/run_monitoring_bot.py``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.alerts import dispatch_availability_alert, dispatch_monitor_alert
from app.db import MonitoredSearch, init_db, session_scope
from providers.provider_manager import search_all_providers
from services.decision_engine import REC_BUY, REC_MILES, build_purchase_recommendation
from services.recommendation_service import rank_flight_options

RUNNABLE_STATUS = "active"
DEFAULT_CHECK_FREQUENCY = timedelta(hours=2)
# Sem data de ida (raro), o rastreio cai neste teto a partir da criação.
TRACK_FALLBACK_WINDOW = timedelta(days=365)
# Variação de preço tolerada para considerar que é "a mesma passagem" ainda no
# ar (preço oscila alguns reais entre verificações). Acima disso, tratamos a
# tarifa rastreada como indisponível.
AVAILABILITY_TOLERANCE = 0.05
# Corroboração anti-alucinação SEM atraso: o alerta sai na hora, mas a tarifa só
# é marcada "confirmada" quando vem de uma fonte de preço real (Travelpayouts/
# conexões) OU quando uma segunda fonte independente, na MESMA busca, traz preço
# equivalente (dentro desta margem). Tarifa solitária de busca web sai marcada
# "a confirmar". Assim não se perde tarifa que some rápido e o fantasma fica
# sinalizado em vez de filtrado.
CORROBORATION_TOLERANCE = 0.05
# Marcadores de fonte que NÃO são preço real (demo/mock/fallback de teste).
_NON_REAL_SOURCE_MARKERS = ("demo", "mock", "fallback")
# Texto-âncora do aviso de indisponibilidade. Guardado em last_status_message,
# ele faz as vezes de "estado": serve para avisar "não está mais disponível" uma
# única vez, sem precisar de uma coluna nova (coluna nova = risco de migração que
# não aplica e derruba todo o monitor).
UNAVAILABLE_STATUS_MESSAGE = "Passagem não está mais disponível — aguardando a próxima oportunidade."


def _already_announced_unavailable(search: MonitoredSearch) -> bool:
    """True se a última verificação já avisou que a passagem sumiu (deriva do
    last_status_message para não repetir o aviso)."""
    return str(search.last_status_message or "").startswith(UNAVAILABLE_STATUS_MESSAGE)


def _source_label(option: dict) -> str:
    return str(option.get("provider") or option.get("source") or "").lower()


def _is_real_price_source(source: str) -> bool:
    """Travelpayouts e conexões montadas a partir dele = preço real (não alucina).
    Busca web (gemini/openai) não entra aqui."""
    return "travelpayouts" in source and not any(m in source for m in _NON_REAL_SOURCE_MARKERS)


def _fare_confidence(best: dict, options: list[dict], tolerance: float = CORROBORATION_TOLERANCE) -> str:
    """'confirmed' quando a tarifa vem de fonte de preço real OU é corroborada
    por outra fonte independente na mesma busca; senão 'unconfirmed'."""
    if _is_real_price_source(_source_label(best)):
        return "confirmed"
    best_price = float(best.get("price_brl") or best.get("price") or 0)
    dep = str(best.get("departure_date") or "")[:10]
    sources: set[str] = set()
    for opt in options:
        if not opt or str(opt.get("departure_date") or "")[:10] != dep:
            continue
        if float(opt.get("price_brl") or opt.get("price") or 0) <= best_price * (1 + tolerance):
            sources.add(_source_label(opt))
    sources.discard("")
    return "confirmed" if len(sources) >= 2 else "unconfirmed"


def is_due(search: MonitoredSearch, now: datetime | None = None) -> bool:
    if (search.status or "").strip().lower() != RUNNABLE_STATUS:
        return False
    if not search.last_checked_at:
        return True
    now = now or datetime.now(timezone.utc)
    last_checked = search.last_checked_at
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)
    return now >= last_checked + DEFAULT_CHECK_FREQUENCY


def is_within_tracking_window(search: MonitoredSearch, now: datetime | None = None) -> bool:
    """Rastreia uma busca ativa ATÉ A VIAGEM acontecer — até o fim do dia da data
    de ida. Antes parava 24h após a criação, o que silenciava buscas legítimas:
    a passagem segue interessando enquanto a viagem não passou. Sem data de ida,
    cai num teto generoso a partir da criação."""
    now = now or datetime.now(timezone.utc)
    dep = getattr(search, "departure_date", None)
    if dep:
        dep_date = dep.date() if isinstance(dep, datetime) else dep
        deadline = datetime(dep_date.year, dep_date.month, dep_date.day, 23, 59, 59, tzinfo=timezone.utc)
        return now <= deadline
    if not search.created_at:
        return True
    created = search.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return now <= created + TRACK_FALLBACK_WINDOW


def get_monitors_to_run(db, now: datetime | None = None, force: bool = False) -> list[MonitoredSearch]:
    rows = list(db.scalars(select(MonitoredSearch)))
    now = now or datetime.now(timezone.utc)
    return [
        s for s in rows
        if (s.status or "").strip().lower() == RUNNABLE_STATUS
        and is_within_tracking_window(s, now)
        and (force or is_due(s, now))
    ]


def query_from_monitor(search: MonitoredSearch) -> dict:
    return {
        "origin": search.origin_iata,
        "destination": search.destination_iata,
        "departure_date": search.departure_date,
        "return_date": search.return_date,
        "adults": search.adults,
        "passengers": search.adults,
        "currency": "BRL",
        "max_price": search.max_price,
    }


def execute_monitored_search(db, search: MonitoredSearch) -> dict:
    """Run one monitored search, send an alert when worthwhile, and update only
    the status-summary fields on the row. Failure-safe: never raises — records
    the error in ``last_status_message`` instead."""
    try:
        offers = search_all_providers(query_from_monitor(search))
    except Exception as exc:  # noqa: BLE001
        search.last_checked_at = datetime.now(timezone.utc)
        search.updated_at = search.last_checked_at
        search.last_status_message = f"Erro na busca: {exc}"[:500]
        return {"ok": False, "message": search.last_status_message}

    options = [_offer_to_option(o, search) for o in offers]
    ranking = rank_flight_options(options, _preferences(search))
    best = ranking.get("recommended_option") or ranking.get("cheapest_option")

    notified = False
    availability_sent = False
    status_message = "Nenhuma tarifa encontrada nesta verificação."

    # Só faz sentido reportar "ainda disponível"/"não está mais disponível"
    # quando já avisamos uma passagem antes (há uma tarifa rastreada).
    tracking_a_fare = bool(search.last_notification_at and search.last_best_price)

    is_alert_candidate = False
    if best:
        rec = _recommendation_for(best, search)
        best_price = best["price_brl"]
        status_message = (
            f"Melhor tarifa: R$ {best_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            + f" — {rec['recommendation']}"
        )
        worth_alert = bool(
            (search.max_price and best_price <= search.max_price)
            or rec["recommendation"] in {REC_BUY, REC_MILES}
        )
        # Só re-alerta quando aparece algo MELHOR (mais barato) do que o último
        # avisado — caso contrário caímos no aviso de disponibilidade abaixo.
        already_notified_recently = bool(
            search.last_notification_at
            and search.last_best_price
            and best_price >= search.last_best_price
        )
        is_alert_candidate = worth_alert and not already_notified_recently
        if is_alert_candidate:
            # Alerta IMEDIATO (não perde tarifa que some rápido). A confiança da
            # tarifa vai num selo: preço real ou corroborado por outra fonte na
            # mesma busca → "confirmada"; tarifa solitária de busca web → "a
            # confirmar". O fantasma fica sinalizado, não escondido.
            confidence = _fare_confidence(best, options)
            status = dispatch_monitor_alert(search, best, rec.get("main_reason"), confidence=confidence)
            notified = status == "sent"
            if notified:
                # last_best_price = preço da passagem AVISADA (a que passamos a
                # rastrear). Ancora a verificação de disponibilidade e o "melhor
                # que o último avisado" — por isso só muda ao alertar.
                search.last_best_price = best_price
                search.last_best_link = best.get("booking_link")

    # ── Sem alerta novo: reportar se a passagem rastreada ainda existe ─────────
    if not notified and tracking_a_fare:
        still_available = bool(best) and best["price_brl"] <= search.last_best_price * (1 + AVAILABILITY_TOLERANCE)
        if still_available:
            # Enquanto continuar disponível, avisa a cada verificação.
            status = dispatch_availability_alert(search, available=True, option=best)
            availability_sent = status == "sent"
            status_message = "Passagem ainda disponível."
        elif not _already_announced_unavailable(search):
            # Sumiu — avisa UMA única vez e volta a aguardar a próxima oportunidade.
            # O "uma vez" é derivado do last_status_message (sem coluna extra).
            status = dispatch_availability_alert(search, available=False)
            availability_sent = status == "sent"
            status_message = UNAVAILABLE_STATUS_MESSAGE
            # Reancora o rastreio: zera o histórico para que a próxima boa tarifa
            # gere um alerta novo, mesmo custando mais que a passagem que sumiu.
            search.last_best_price = None
            search.last_notification_at = None

    search.last_checked_at = datetime.now(timezone.utc)
    search.updated_at = search.last_checked_at
    # last_best_price/last_best_link são atualizados apenas quando um alerta é
    # efetivamente enviado (acima) — refletem a passagem avisada, não toda
    # cotação vista. O status corrente da busca vai em last_status_message.
    search.last_status_message = status_message[:500]
    if notified:
        search.last_notification_at = datetime.now(timezone.utc)

    return {
        "ok": True,
        "message": status_message,
        "notified": notified,
        "availability_sent": availability_sent,
    }


def run_due_monitors(force: bool = False) -> dict:
    init_db()
    with session_scope() as db:
        # Diagnóstico explícito: por que rodou (ou não) cada busca. Aparece no
        # log do GitHub Actions e distingue "banco sem buscas" (provável banco
        # diferente entre app e bot) de "buscas existem mas expiraram/pausadas".
        now = datetime.now(timezone.utc)
        all_rows = list(db.scalars(select(MonitoredSearch)))
        active = [s for s in all_rows if (s.status or "").strip().lower() == RUNNABLE_STATUS]
        in_window = [s for s in active if is_within_tracking_window(s, now)]
        total = len(all_rows)
        print(
            f"[monitor] buscas no banco={total} | ativas={len(active)} | "
            f"em_rastreio(ate_a_viagem)={len(in_window)} | pausadas={total - len(active)} | "
            f"viagem_ja_passou={len(active) - len(in_window)}"
        )
        if total == 0:
            print(
                "[monitor] NENHUMA busca no banco que o bot lê. Se você criou buscas no app, "
                "o app e o bot estão em bancos diferentes: confira se DATABASE_URL é o MESMO "
                "nos secrets do Streamlit e do GitHub Actions."
            )
        elif len(in_window) == 0:
            print(
                "[monitor] Há buscas, mas nenhuma em rastreio (a data de ida já passou, ou "
                "estão pausadas). Crie uma busca com data de ida futura."
            )

        searches = get_monitors_to_run(db, now=now, force=force)
        checked = 0
        notified = 0
        availability_updates = 0
        errors = 0
        for search in searches:
            # Defesa: uma falha numa busca (envio, dados estranhos) não pode
            # derrubar o lote inteiro e silenciar as demais.
            try:
                result = execute_monitored_search(db, search)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"[monitor] busca {getattr(search, 'id', '?')} falhou: {exc}")
                continue
            checked += 1
            if result.get("notified"):
                notified += 1
            if result.get("availability_sent"):
                availability_updates += 1
        return {
            "monitors_checked": checked,
            "alerts_sent": notified,
            "availability_updates": availability_updates,
            "errors": errors,
            "total_in_db": total,
            "active": len(active),
            "in_window": len(in_window),
        }


def _preferences(search: MonitoredSearch) -> dict:
    return {
        "max_price": search.max_price,
        "max_stops": search.max_stops,
        "max_duration_minutes": search.max_duration_minutes,
        "min_mile_value": search.min_mile_value,
    }


def _recommendation_for(option: dict, search: MonitoredSearch) -> dict:
    return build_purchase_recommendation(
        [option],
        {
            "max_price": search.max_price,
            "consider_miles": search.consider_miles,
            "user_min_mile_value": search.min_mile_value,
            "departure_date": search.departure_date,
        },
    )


def _offer_to_option(offer: dict, search: MonitoredSearch) -> dict:
    from services.miles_service import enrich_deal_with_miles

    deal = {
        "price_brl": float(offer.get("price") or 0),
        "airline": offer.get("airline") or "",
        "provider": offer.get("provider") or offer.get("source") or "",
        "stops": offer.get("stops"),
        "duration_minutes": offer.get("duration_minutes"),
        "departure_date": offer.get("departure_date") or search.departure_date,
        "return_date": offer.get("return_date") or search.return_date,
        "booking_link": offer.get("booking_link") or "",
        "origin_iata": offer.get("origin") or search.origin_iata,
        "destination_iata": offer.get("destination") or search.destination_iata,
        "score": int(offer.get("score") or 0),
        # Detalhamento ida/volta — necessario para o alerta deixar claro se o
        # preco e o total da viagem (ida + volta) ou somente um trecho.
        "price_outbound": offer.get("price_outbound"),
        "price_return": offer.get("price_return"),
        "price_note": offer.get("price_note"),
    }
    return enrich_deal_with_miles(deal, search.min_mile_value or 0.035)
