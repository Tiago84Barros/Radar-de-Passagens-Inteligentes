from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select

from app.deals import calculate_deal_score
from app.db import AlertLog, FlightQuote, FlightSearch, ProviderLog, database_diagnostics, init_db, session_scope
from app.formatting import format_brl
from app.location_resolver import LocationResolution, resolve_location
try:
    from app.location_resolver import search_locations as resolver_search_locations
except ImportError:
    def resolver_search_locations(value: str) -> list[LocationResolution]:
        location = resolve_location(value)
        return [location] if location else []
from app.monitor import run_due_searches, run_search_once
from app.settings import get_settings
from app.styles import load_custom_css
from components.cards import render_airline_comparison, render_deal_cards_section, render_origin_card
from components.airport_cards import render_airport_cards
from components.fare_cards import render_fare_cards
from components.charts import render_current_prices_bar, render_future_projection
from components.monitor_prompt import render_monitor_prompt
from data.destinations_catalog import BRAZIL_IATAS, get_destination_info
from providers.travelpayouts_provider import TravelPayoutsProvider, TravelPayoutsProviderError
from services.air_network import find_candidate_hubs, hub_route_label
from services.github_actions_service import is_configured as github_trigger_configured, trigger_monitor
from services.miles_service import DEFAULT_CENTS_PER_MILE, estimate_miles, format_miles
from services.opportunity_service import (
    get_airline_comparison,
    get_best_miles_deal,
    get_home_deals,
    get_international_lowest,
    get_national_lowest,
)


st.set_page_config(
    page_title="Radar de Passagens Inteligentes",
    page_icon="✈️",
    layout="wide",
)


FLEXIBILITY_OPTIONS = {
    "exata": False,
    "±3 dias": True,
    "±7 dias": True,
    "mês inteiro": True,
}
FREQUENCY_OPTIONS = {"30 min": 30, "1h": 60, "3h": 180, "6h": 360}
TRIP_TYPE_OPTIONS = {"ida": "one_way", "ida e volta": "round_trip"}
OPPORTUNITY_LABELS = {
    "normal": "Normal",
    "boa_oportunidade": "Boa",
    "excelente_oportunidade": "Excelente",
    "oportunidade_rara": "Ótima",
    "Normal": "Normal",
    "Boa oportunidade": "Boa oportunidade",
    "Ótima oportunidade": "Ótima oportunidade",
    "Excelente oportunidade": "Excelente oportunidade",
}

NON_REAL_SOURCE_MARKERS = ("mock", "demo", "fallback", "demonstracao", "demonstra")

# Freshness window for the Home fare cards. Airfares expire fast, so by default
# the Home tab only shows fares collected in the last 48h; the user can widen it.
FARE_WINDOW_OPTIONS: dict[str, float | None] = {
    "24h": 24.0,
    "48h": 48.0,
    "7 dias": 168.0,
    "Todas": None,
}
FARE_WINDOW_DEFAULT_INDEX = 1  # "48h"


# ─── Auth ─────────────────────────────────────────────────────────────────────

def require_password() -> None:
    settings = get_settings()
    if not settings.app_password:
        return
    if st.session_state.get("authenticated"):
        return
    load_custom_css()

    # Centered, professional login card. Branding lives INSIDE the form so the
    # whole thing reads as one cohesive card; the card styling is scoped to the
    # login form via a :has(.login-brand) selector so the app's other forms
    # are unaffected.
    st.markdown('<div class="login-page"></div>', unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.25, 1])
    with mid:
        with st.form("login_form", clear_on_submit=False):
            st.markdown(
                '<div class="login-brand">'
                '<div class="login-logo">✈️</div>'
                '<div class="login-title">Radar de Passagens</div>'
                '<div class="login-title">Inteligentes</div>'
                '<div class="login-subtitle">Monitoramento de tarifas e oportunidades de voos</div>'
                '<div class="login-divider"></div>'
                '<div class="login-prompt">🔒 Área restrita — informe sua senha para continuar</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            password = st.text_input(
                "Senha de acesso",
                type="password",
                placeholder="Digite sua senha",
            )
            submitted = st.form_submit_button("Entrar", type="primary", use_container_width=True)
        if submitted:
            if password == settings.app_password:
                st.session_state["authenticated"] = True
                st.rerun()
            st.error("Senha inválida. Verifique e tente novamente.")
        st.markdown(
            '<div class="login-footer">Acesso protegido · uso pessoal</div>',
            unsafe_allow_html=True,
        )
    st.stop()


# ─── DB seed ──────────────────────────────────────────────────────────────────

def seed_if_empty(enable_demo_seed: bool) -> None:
    if not enable_demo_seed:
        return
    with session_scope() as db:
        exists = db.scalar(select(func.count()).select_from(FlightSearch)) or 0
        if exists:
            return
        demo = FlightSearch(
            owner_email="demo@radar.local",
            origin="GRU",
            destination="LIS",
            departure_date=date.today() + timedelta(days=70),
            return_date=date.today() + timedelta(days=84),
            flexible_dates=True,
            adults=1,
            passengers=1,
            max_price=3200,
            currency="BRL",
            trip_type="round_trip",
            baggage_included=True,
            frequency_minutes=60,
        )
        db.add(demo)
        db.flush()
        run_search_once(db, demo)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def money(value: Any, currency: str = "R$") -> str:
    return format_brl(None if value is None or pd.isna(value) else float(value))


def safe_datetime_series(values: Any) -> pd.Series:
    try:
        return pd.to_datetime(values, utc=True, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(values, utc=True, errors="coerce")


def safe_datetime(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    parsed = safe_datetime_series(pd.Series([value])).iloc[0]
    if pd.isna(parsed):
        return None
    return parsed


def format_datetime(value: Any) -> str:
    parsed = safe_datetime(value)
    if parsed is None:
        return "-"
    return parsed.strftime("%d/%m/%Y %H:%M")


def format_date(value: Any) -> str:
    parsed = safe_datetime(value)
    if parsed is None:
        return "-"
    return parsed.strftime("%d/%m/%Y")


def get_provider_status(settings) -> dict[str, Any]:
    providers = {
        "Travelpayouts API": bool(settings.travelpayouts_api_token),
        "Azul scraping": bool(settings.enable_airline_scrapers),
        "GOL scraping": bool(settings.enable_airline_scrapers),
        "LATAM scraping": bool(settings.enable_airline_scrapers),
    }
    active = [name for name, configured in providers.items() if configured]
    return {
        "providers": providers,
        "active_names": active,
        "demo_mode": not bool(settings.travelpayouts_api_token),
        "provider_label": ", ".join(active) if active else "Nenhuma fonte real configurada",
        "amadeus_env": settings.amadeus_env,
    }


def is_real_provider_name(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and not any(marker in text for marker in NON_REAL_SOURCE_MARKERS)


def filter_real_quotes_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "provedor" not in df.columns:
        return df.copy()
    return df[df["provedor"].map(is_real_provider_name)].copy()


def route_context_from_latest(summary: dict) -> dict[str, Any] | None:
    session_context = st.session_state.get("last_route_context")
    if session_context:
        return session_context
    searches = summary.get("searches") or []
    if not searches:
        return None
    search = searches[0]
    origin = str(search.origin or "").upper()
    destination = str(search.destination or "").upper()
    return {
        "origin_code": origin,
        "origin_label": origin,
        "destination_code": destination,
        "destination_label": destination,
        "departure_date": search.departure_date,
        "return_date": search.return_date,
        "source": "Ultima busca cadastrada",
    }


def duration_label(minutes: int | None) -> str:
    if not minutes:
        return "-"
    hours, mins = divmod(int(minutes), 60)
    return f"{hours}h {mins:02d}min"


def frequency_label(minutes: int | None) -> str:
    labels = {30: "30 min", 60: "1h", 180: "3h", 360: "6h", 720: "12h"}
    return labels.get(int(minutes or 0), f"{minutes} min")


def status_badge(label: str, status: str = "neutral") -> str:
    return f'<span class="status-pill status-{status}">{label}</span>'


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_summary() -> dict:
    with session_scope() as db:
        active = db.scalar(select(func.count()).select_from(FlightSearch).where(FlightSearch.is_active.is_(True))) or 0
        alerts = db.scalar(select(func.count()).select_from(AlertLog)) or 0
        quotes = list(db.scalars(select(FlightQuote).order_by(FlightQuote.detected_at.desc()).limit(5000)))
        searches = list(db.scalars(select(FlightSearch).order_by(FlightSearch.created_at.desc())))
        latest_search = db.scalar(select(func.max(FlightSearch.last_checked_at)))
        latest_provider_log = db.scalar(
            select(ProviderLog)
            .where(ProviderLog.provider == "travelpayouts")
            .order_by(ProviderLog.created_at.desc())
            .limit(1)
        )
        latest_alert_by_quote = {
            quote_id: status
            for quote_id, status in db.execute(
                select(AlertLog.quote_id, AlertLog.status).where(AlertLog.quote_id.is_not(None))
            )
        }
        routes = len({f"{search.origin}-{search.destination}" for search in searches})
    return {
        "active": active,
        "alerts": alerts,
        "quotes": quotes,
        "searches": searches,
        "latest_search": latest_search,
        "latest_provider_log": latest_provider_log,
        "latest_alert_by_quote": latest_alert_by_quote,
        "routes": routes,
    }


def quotes_df(quotes: list[FlightQuote], searches: list[FlightSearch], alerts_by_quote: dict[int, str]) -> pd.DataFrame:
    search_map = {search.id: search for search in searches}
    rows = []
    for quote in quotes:
        search = search_map.get(quote.search_id)
        max_price = search.max_price if search else None
        economy = (max_price - quote.price) if max_price is not None else None
        deal = calculate_deal_score({"price": quote.price}, max_price, [])
        # Extract via_hub info from raw_payload if stored
        via_hub = ""
        try:
            import json as _json
            rp = quote.raw_payload
            if isinstance(rp, str):
                rp = _json.loads(rp)
            if isinstance(rp, dict):
                via_hub = str(rp.get("via_hub") or "")
        except Exception:
            pass

        route_label = (
            hub_route_label(quote.origin, via_hub, quote.destination)
            if via_hub else
            f"{quote.origin} → {quote.destination}"
        )
        rows.append(
            {
                "id": quote.id,
                "search_id": quote.search_id,
                "rota": route_label,
                "origem": quote.origin,
                "destino": quote.destination,
                "via_hub": via_hub,
                "ida": quote.departure_date,
                "volta": quote.return_date,
                "companhia": quote.airline,
                "preço": quote.price,
                "preço máximo": max_price,
                "economia": economy,
                "score": deal["score"],
                "moeda": quote.currency,
                "duração_min": quote.duration_minutes,
                "duração": duration_label(quote.duration_minutes),
                "escalas": quote.stops,
                "provedor": quote.provider,
                "oportunidade": quote.opportunity,
                "classificação": OPPORTUNITY_LABELS.get(quote.opportunity, quote.opportunity),
                "detectado_em": quote.collected_at or quote.detected_at,
                "is_current": bool(getattr(quote, "is_current", True)),
                "link": quote.booking_link,
                "alerta": alerts_by_quote.get(quote.id, "-"),
            }
        )
    return pd.DataFrame(rows)


def searches_df(searches: list[FlightSearch], df_quotes: pd.DataFrame) -> pd.DataFrame:
    lowest_by_search = {}
    if not df_quotes.empty:
        lowest_by_search = df_quotes.groupby("search_id")["preço"].min().to_dict()
    return pd.DataFrame(
        [
            {
                "id": search.id,
                "status": "Ativa" if search.is_active else "Pausada",
                "origem": search.origin,
                "destino": search.destination,
                "data de ida": search.departure_date,
                "data de volta": search.return_date,
                "preço máximo": search.max_price,
                "frequência": frequency_label(search.frequency_minutes),
                "última consulta": search.last_checked_at,
                "menor preço encontrado": lowest_by_search.get(search.id),
                "ação": "Pausar" if search.is_active else "Reativar",
            }
            for search in searches
        ]
    )


def build_metrics(summary: dict, df: pd.DataFrame) -> dict[str, Any]:
    recent = pd.DataFrame()
    if not df.empty:
        detected_at = safe_datetime_series(df["detectado_em"])
        recent = df[detected_at >= (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24))]
    positive_economy = df["economia"].clip(lower=0).sum() if not df.empty and "economia" in df else 0
    alerts_sent = 0
    if not df.empty and "alerta" in df:
        alert_values = df["alerta"].astype(str)
        alerts_sent = int((~alert_values.isin(["-", "failed"]) & ~alert_values.str.startswith("failed")).sum())
    latest_real_search = summary["latest_search"]
    if not df.empty and "detectado_em" in df:
        latest_detected = safe_datetime_series(df["detectado_em"]).max()
        latest_real_search = None if pd.isna(latest_detected) else latest_detected
    classified = {"boa_oportunidade", "excelente_oportunidade", "oportunidade_rara", "Boa oportunidade", "Ótima oportunidade", "Excelente oportunidade"}
    return {
        "active": summary["active"],
        "alerts": alerts_sent,
        "lowest_24h": None if recent.empty else recent["preço"].min(),
        "economy": positive_economy,
        "opportunities": 0 if df.empty else int(df["oportunidade"].isin(classified).sum()),
        "latest_search": latest_real_search,
    }


# ─── Shared render helpers ────────────────────────────────────────────────────

def render_metric_cards(values: list[tuple], per_row: int = 4) -> None:
    for start in range(0, len(values), per_row):
        cols = st.columns(min(per_row, len(values) - start))
        for col, metric in zip(cols, values[start:start + per_row]):
            label, value, help_text = metric[:3]
            indicator = metric[3] if len(metric) > 3 else "Atualizado"
            tooltip = metric[4] if len(metric) > 4 else ""
            info_icon = (
                f'<span class="metric-info" title="{tooltip}">ⓘ</span>' if tooltip else ""
            )
            col.markdown(
                f"""
                <div class="metric-card" title="{tooltip}">
                    <div class="metric-label">{label}{info_icon}</div>
                    <div class="metric-value">{value}</div>
                    <div class="metric-help">{help_text}</div>
                    <div class="metric-indicator">{indicator}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ─── Location picker ──────────────────────────────────────────────────────────

def _resolve_search_location(value: str, field_label: str) -> LocationResolution | None:
    location = resolve_location(value)
    if location:
        return location
    st.error(f"Nao consegui identificar {field_label}. Use codigo IATA, cidade, aeroporto ou pais. Exemplos: BEL, Belem, Lisboa, Portugal.")
    return None


def _location_option_label(location: LocationResolution) -> str:
    source_type = "Aeroporto" if location.location_type == "airport" else "Cidade/area"
    return f"{location.label} - {source_type}"


def _render_location_picker(label: str, key: str) -> tuple[str, LocationResolution | None]:
    query = st.text_input(
        label,
        value="",
        key=f"{key}_query",
        placeholder="Cidade, pais ou codigo do aeroporto",
        help="Digite cidade, pais, aeroporto ou codigo IATA. Ex.: Belem, Orlando, Lisboa, BEL.",
    ).strip()
    if not query:
        st.caption("Digite para ver os aeroportos e codigos disponiveis.")
        return query, None

    options = resolver_search_locations(query)
    if not options:
        st.caption("Nenhum aeroporto encontrado para esse texto.")
        return query, None

    selected = st.selectbox(
        f"Aeroporto para {label.lower()}",
        options,
        key=f"{key}_airport",
        format_func=_location_option_label,
    )
    return query, selected


# ─── Header ───────────────────────────────────────────────────────────────────

def render_header(provider_status: dict[str, Any], latest_provider_log: ProviderLog | None = None) -> None:
    load_custom_css()
    if provider_status["demo_mode"]:
        st.markdown(
            '<div class="demo-banner">⚠️ Modo demonstração: configure o token Travelpayouts na sidebar para buscar passagens reais.</div>',
            unsafe_allow_html=True,
        )
    elif latest_provider_log and latest_provider_log.status == "real_failed_fallback":
        st.markdown(
            f'<div class="demo-banner">⚠️ Travelpayouts configurada, mas a ultima consulta falhou e usou fallback demo. '
            f'Motivo: {latest_provider_log.error_message or "erro nao informado"}</div>',
            unsafe_allow_html=True,
        )
    elif latest_provider_log and latest_provider_log.status == "real_empty":
        st.markdown(
            '<div class="demo-banner">ℹ️ Travelpayouts respondeu, mas nao encontrou cotacoes para a ultima rota/data pesquisada.</div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        f"""
        <div class="top-shell">
            <div>
                <div class="top-kicker">✈️ Monitoramento inteligente de tarifas aéreas</div>
                <p class="radar-title">Radar de Passagens Inteligentes</p>
                <div class="radar-subtitle">
                    Encontre oportunidades em dinheiro e milhas para viajar melhor pagando menos.
                </div>
            </div>
            <div class="hero-status">
                <div class="hero-status-title">Status operacional</div>
                {status_badge("Modo demo", "warn") if provider_status["demo_mode"] else status_badge("API real ativa", "ok")}
                <div class="opportunity-detail" style="margin-top:8px;color:#9AA8BC;font-size:.82rem;">
                    Provider: {provider_status["provider_label"]}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─── Sidebar ──────────────────────────────────────────────────────────────────

def render_sidebar(summary: dict, provider_status: dict[str, Any], db_connected: bool) -> None:
    settings = get_settings()
    with st.sidebar:
        st.title("✈️ Radar de Passagens")
        st.caption("Painel de controle")

        st.subheader("🔍 Nova busca de passagem")
        if st.session_state.get("last_location_resolution"):
            st.info(st.session_state["last_location_resolution"])
        # Feedback from the previous submit (survives st.rerun via session_state)
        _save_fb = st.session_state.pop("last_search_feedback", None)
        if _save_fb:
            st.success(_save_fb["text"])
        _trig_fb = st.session_state.pop("last_trigger_feedback", None)
        if _trig_fb:
            _lvl = _trig_fb.get("level", "info")
            if _lvl == "warning":
                st.warning(_trig_fb["text"])
            elif _lvl == "caption":
                st.caption(_trig_fb["text"])
            else:
                st.info(_trig_fb["text"])
        origin_input, selected_origin = _render_location_picker("Origem", "origin")
        destination_input, selected_destination = _render_location_picker("Destino", "destination")

        # Make the chosen origin available to the Home tab immediately (before
        # submitting the search) so it can render the origin postcard card.
        if selected_origin is not None:
            st.session_state["home_origin"] = {
                "code": selected_origin.code,
                "label": selected_origin.label,
            }
        elif not origin_input:
            st.session_state.pop("home_origin", None)

        if selected_destination is not None:
            st.session_state["home_destination"] = {
                "code": selected_destination.code,
                "label": selected_destination.label,
            }
        elif not destination_input:
            st.session_state.pop("home_destination", None)

        with st.form("new_search_form", clear_on_submit=False):
            departure = st.date_input("Data de ida", value=None, format="DD/MM/YYYY")
            trip_label = st.selectbox("Tipo de viagem", list(TRIP_TYPE_OPTIONS.keys()), index=1)
            return_date = st.date_input(
                "Data de volta",
                value=None,
                disabled=TRIP_TYPE_OPTIONS[trip_label] == "one_way",
                format="DD/MM/YYYY",
            )
            adults = st.number_input("Adultos", min_value=1, max_value=9, value=1)
            max_price = st.number_input("Preço máximo (R$)", min_value=100.0, value=3200.0, step=50.0)
            currency = st.selectbox("Moeda", ["BRL", "USD", "EUR"], index=0)
            flexibility = st.selectbox("Flexibilidade de datas", list(FLEXIBILITY_OPTIONS.keys()))
            frequency_label_selected = st.selectbox("Frequência de busca", list(FREQUENCY_OPTIONS.keys()), index=1)

            st.markdown("**Opções de alerta**")
            search_miles = st.toggle("Buscar em milhas", value=False, help="Habilita busca comparativa em milhas (estimada)")
            telegram_enabled = st.toggle(
                "Alertas via Telegram",
                value=bool(settings.telegram_bot_token and settings.telegram_chat_id),
            )

            search_now = st.form_submit_button("🔍 Buscar agora", use_container_width=True)
            start_monitoring = st.form_submit_button("🛰️ Iniciar monitoramento", type="primary", use_container_width=True)

        if search_now or start_monitoring:
            origin_location = selected_origin or _resolve_search_location(origin_input, "a origem")
            destination_location = selected_destination or _resolve_search_location(destination_input, "o destino")
            if not origin_location or not destination_location:
                pass
            elif departure is None:
                st.warning("Informe a data de ida antes de buscar.")
            elif telegram_enabled and not (settings.telegram_bot_token and settings.telegram_chat_id):
                st.warning("Telegram marcado, mas os secrets do Telegram ainda não estão configurados.")
            else:
                st.session_state["last_location_resolution"] = (
                    f"✅ Busca: {origin_location.label} → {destination_location.label}"
                )
                st.session_state["last_route_context"] = {
                    "origin_code": origin_location.code,
                    "origin_label": origin_location.label,
                    "destination_code": destination_location.code,
                    "destination_label": destination_location.label,
                    "departure_date": departure,
                    "return_date": return_date if TRIP_TYPE_OPTIONS[trip_label] == "round_trip" else None,
                    "source": "Busca feita agora" if search_now else "Monitoramento iniciado",
                }
                with session_scope() as db:
                    search = FlightSearch(
                        owner_email="demo@radar.local",
                        origin=origin_location.code,
                        destination=destination_location.code,
                        departure_date=departure,
                        return_date=return_date if TRIP_TYPE_OPTIONS[trip_label] == "round_trip" else None,
                        flexible_dates=FLEXIBILITY_OPTIONS[flexibility],
                        adults=int(adults),
                        passengers=int(adults),
                        max_price=float(max_price),
                        currency=currency,
                        trip_type=TRIP_TYPE_OPTIONS[trip_label],
                        baggage_included=False,
                        frequency_minutes=FREQUENCY_OPTIONS[frequency_label_selected],
                        is_active=bool(start_monitoring),
                    )
                    db.add(search)
                    db.flush()
                    saved = run_search_once(db, search, include_year_calendar=True)
                if start_monitoring:
                    save_msg = f"🛰️ Monitoramento iniciado. {saved} cotação(ões) salvas."
                else:
                    save_msg = f"✅ Busca concluída. {saved} cotação(ões) salvas."

                # Fire the scraping workflow on GitHub Actions right away so the
                # full scraping (Google/GOL/LATAM/Azul) runs immediately instead
                # of waiting for the next scheduled cron. The cron keeps running
                # on its own, so monitoring continues even with the app closed.
                trigger_msg = None
                trigger_level = "info"
                if github_trigger_configured():
                    dispatch = trigger_monitor(force=True)
                    if dispatch.ok:
                        trigger_msg = (
                            "🚀 " + dispatch.message + " Atualize a página em ~2-3 min "
                            "para ver os preços por companhia (R$ e milhas)."
                        )
                        trigger_level = "info"
                    else:
                        trigger_msg = "⚠️ " + dispatch.message
                        trigger_level = "warning"
                else:
                    trigger_msg = (
                        "ℹ️ Para coletar os preços agora via scraping, configure GITHUB_TOKEN e "
                        "GITHUB_REPO. Sem isso, o monitor agendado coleta em até 30 min."
                    )
                    trigger_level = "caption"

                # Persist feedback across the rerun below (messages set here would
                # otherwise be wiped by st.rerun()).
                st.session_state["last_search_feedback"] = {"text": save_msg, "level": "success"}
                st.session_state["last_trigger_feedback"] = {"text": trigger_msg, "level": trigger_level}
                st.rerun()

        st.divider()
        st.subheader("📡 Status do sistema")
        telegram_ok = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        status_rows = [
            ("Banco conectado", "✅ Sim" if db_connected else "❌ Não"),
            ("Provider ativo", provider_status["provider_label"]),
            ("Travelpayouts", "✅ Ativo" if settings.travelpayouts_api_token else "⚠️ Inativo"),
            ("Modo", "⚠️ Demonstração" if provider_status["demo_mode"] else "✅ Travelpayouts real"),
            ("Telegram", "✅ Configurado" if telegram_ok else "⚠️ Não configurado"),
            ("Última busca", format_datetime(summary.get("latest_search"))),
            ("Buscas ativas", summary["active"]),
        ]
        latest_provider_log = summary.get("latest_provider_log")
        if latest_provider_log:
            status_rows.insert(3, ("Status API", latest_provider_log.status))
        for label, value in status_rows:
            st.markdown(
                f'<div class="status-row"><span class="status-label">{label}</span>'
                f'<span class="status-value">{value}</span></div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # ── Malha aérea: show candidate hubs for last search ──────────────
        last_ctx = st.session_state.get("last_route_context")
        if last_ctx:
            orig = last_ctx.get("origin_code", "")
            dest = last_ctx.get("destination_code", "")
            if orig and dest:
                hubs = find_candidate_hubs(orig, dest, max_hubs=3)
                hub_str = " · ".join(hubs) if hubs else "direto"
                st.markdown(
                    f'<div class="malha-info">'
                    f'<div class="malha-title">🔗 Malha aérea expandida</div>'
                    f'<div class="malha-desc">Busca automática de conexões via hubs:</div>'
                    f'<div class="malha-hubs">{hub_str}</div>'
                    f'<div class="malha-route">{orig} → {hub_str.split(" · ")[0] if hubs else "–"} → {dest}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        if st.button("▶️ Rodar buscas devidas agora", use_container_width=True):
            result = run_due_searches(force=False)
            st.success(f"{result['searches_checked']} buscas checadas; {result['quotes_saved']} cotações salvas.")
            st.rerun()


# ─── Tab: Início ──────────────────────────────────────────────────────────────

def render_home_metrics(summary: dict, df: pd.DataFrame) -> None:
    """6 KPI cards for the home screen."""
    metrics_base = build_metrics(summary, df)

    nat_lowest = get_national_lowest(df)
    intl_lowest = get_international_lowest(df)
    best_miles = get_best_miles_deal(df)

    best_miles_label = "Dados Ausentes"
    if best_miles:
        miles = best_miles.get("estimated_miles") or 0
        best_miles_label = format_miles(miles) if miles else "Dados Ausentes"

    render_metric_cards(
        [
            (
                "Buscas ativas",
                metrics_base["active"],
                "Rotas que você cadastrou e o radar monitora sozinho",
                "Online",
                "Quantas rotas estão em monitoramento. O monitor as verifica automaticamente "
                "a cada 30 min (no GitHub Actions), mesmo com o app fechado, e salva os preços no banco.",
            ),
            (
                "Oportunidades",
                metrics_base["opportunities"],
                "Cotações classificadas como Boa, Ótima ou Excelente",
                "Score ativo",
                "Número de cotações cujo preço, comparado ao histórico da rota, recebeu uma boa nota "
                "(score). Quanto melhor o desconto, maior a classificação.",
            ),
            (
                "Menor preço nacional",
                money(nat_lowest) if nat_lowest else "Dados Ausentes",
                "Voo mais barato dentro do Brasil já coletado",
                "Nacional",
                "Menor tarifa em reais encontrada para voos entre cidades brasileiras, considerando "
                "todas as cotações reais salvas no banco. 'Dados Ausentes' = nenhum voo nacional coletado ainda.",
            ),
            (
                "Menor preço internacional",
                money(intl_lowest) if intl_lowest else "Dados Ausentes",
                "Voo mais barato para o exterior já coletado",
                "Internacional",
                "Menor tarifa em reais encontrada para voos com destino fora do Brasil, considerando "
                "todas as cotações reais salvas. 'Dados Ausentes' = nenhum voo internacional coletado ainda.",
            ),
            (
                "Melhor em milhas",
                best_miles_label,
                "Estimativa de milhas do voo mais barato",
                "Milhas",
                "Estimativa de quantas milhas equivaleriam ao voo mais barato (preço ÷ R$ 0,035). "
                "É um cálculo aproximado — NÃO representa disponibilidade real em Smiles, TudoAzul ou Latam Pass.",
            ),
            (
                "Alertas enviados",
                metrics_base["alerts"],
                "Avisos de preço já disparados a você",
                "Histórico",
                "Quantas notificações de oportunidade já foram enviadas por Telegram/e-mail quando um "
                "preço dentro do seu limite foi encontrado.",
            ),
        ],
        per_row=3,
    )


def _clean_city_from_label(label: str, code: str) -> str:
    """Extract a readable city name from a LocationResolution label.

    Labels look like 'Belém, Brasil (BEL)' — we want just 'Belém'.
    """
    text = (label or "").strip()
    if not text:
        return code
    # Drop a trailing ' (XXX)' airport code
    if "(" in text:
        text = text.split("(", 1)[0].strip()
    # Keep only the city part (before the first comma)
    if "," in text:
        text = text.split(",", 1)[0].strip()
    return text or code


def render_home_origin_card() -> None:
    """Render the origin postcard card at the top of the Home tab when the user
    has chosen an origin in the sidebar. Shows IATA code, city and postcard image."""
    origin = st.session_state.get("home_origin")
    if not origin:
        return
    code = str(origin.get("code") or "").upper()
    if not code:
        return
    info = get_destination_info(code)
    catalog_city = info.get("city") or ""
    city = catalog_city if catalog_city and catalog_city.upper() != code else _clean_city_from_label(origin.get("label", ""), code)
    render_origin_card(
        iata=code,
        city=city,
        country=info.get("country", ""),
        image_url=info.get("image_url", ""),
        gradient=info.get("gradient", ""),
        postcard_label=info.get("postcard_label", ""),
    )


def _home_route_dict(origin_code: str, dest_code: str, last_ctx: dict) -> dict:
    """Assemble the route dict used by the monitor button and the future
    projection chart, taking dates from the last search context when available."""
    matches = (
        str(last_ctx.get("origin_code") or "").upper() == origin_code
        and str(last_ctx.get("destination_code") or "").upper() == dest_code
    )
    return {
        "origin_code": origin_code,
        "destination_code": dest_code,
        "departure_date": last_ctx.get("departure_date") if matches else None,
        "return_date": last_ctx.get("return_date") if matches else None,
        "adults": 1,
        "max_price": 3200.0,
        "currency": "BRL",
        "trip_type": "round_trip",
        "frequency_minutes": 60,
    }


def _empty_state(message: str) -> None:
    st.markdown(
        f'<div class="home-empty">{message}</div>',
        unsafe_allow_html=True,
    )


def render_home_tab(summary: dict, df_quotes: pd.DataFrame, provider_status: dict) -> None:
    """Home screen orchestration.

    Flow (driven by the sidebar pickers):
      • no origin            → elegant empty state.
      • origin only          → origin postcard + "choose destination" hint.
      • origin + destination → both postcards. Before a search, a "click Buscar
        agora" hint; after a search, the fare cards, price-comparison bar chart,
        future-projection chart and the "Monitorar esta rota 24h" button.
    """
    origin = st.session_state.get("home_origin") or {}
    destination = st.session_state.get("home_destination") or {}
    origin_code = str(origin.get("code") or "").upper()
    dest_code = str(destination.get("code") or "").upper()

    if not origin_code:
        _empty_state("🧭 Escolha uma origem e um destino na lateral para iniciar o radar.")
        return

    # Origin (and destination, if chosen) postcards.
    render_airport_cards(origin_code, dest_code or None)

    if not dest_code:
        _empty_state("📍 Agora escolha o destino para comparar oportunidades.")
        return

    last_ctx = st.session_state.get("last_route_context") or {}
    searched = (
        str(last_ctx.get("origin_code") or "").upper() == origin_code
        and str(last_ctx.get("destination_code") or "").upper() == dest_code
    )
    # Any quote ever collected for this route (ignores freshness) — used only to
    # decide between the "click Buscar agora" hint and the fare section.
    deals_any = get_airline_comparison(df_quotes, origin_code, dest_code)

    # Both chosen but no search yet and no quotes collected for the route.
    if not searched and not deals_any:
        _empty_state("🔍 Clique em <strong>Buscar agora</strong> para consultar as melhores tarifas.")
        return

    st.divider()

    # Validity window: airfares expire fast, so by default we only surface fares
    # collected recently. The user can widen the window (or see everything).
    window_label = st.radio(
        "Mostrar tarifas coletadas nas últimas:",
        list(FARE_WINDOW_OPTIONS.keys()),
        index=FARE_WINDOW_DEFAULT_INDEX,
        horizontal=True,
        key="fare_window",
        help="As tarifas expiram rápido. Esta janela esconde preços antigos que "
        "podem não existir mais. O histórico completo continua na aba Histórico.",
    )
    max_age_hours = FARE_WINDOW_OPTIONS[window_label]
    deals = get_airline_comparison(
        df_quotes, origin_code, dest_code, max_age_hours=max_age_hours
    )

    # Searched (or has history) but everything is older than the chosen window.
    if deals_any and not deals:
        _empty_state(
            "⏳ Nenhuma tarifa coletada nesta janela de tempo. As tarifas mais "
            "recentes podem ter expirado — amplie a janela acima ou clique em "
            "<strong>Buscar agora</strong> para atualizar os preços."
        )
        return

    # Best fare per airline (cheapest highlighted). Handles its own empty state.
    render_fare_cards(deals)

    if deals:
        st.divider()
        render_current_prices_bar(deals)

    # Future 12-month projection (real data when available, else a clearly
    # marked simulation seeded from the cheapest current fare).
    base_price = None
    if deals:
        prices = [float(d.get("price_brl") or 0) for d in deals if (d.get("price_brl") or 0) > 0]
        base_price = min(prices) if prices else None
    st.divider()
    render_future_projection(df_quotes, origin_code, dest_code, base_price)

    # "Monitorar esta rota 24h" with keep/replace/cancel conflict handling.
    st.divider()
    render_monitor_prompt(_home_route_dict(origin_code, dest_code, last_ctx))


# ─── Tab: Oportunidades ───────────────────────────────────────────────────────

def render_opportunities(df: pd.DataFrame) -> None:
    st.subheader("Oportunidades encontradas")
    if df.empty:
        st.info("Nenhuma passagem encontrada ainda. Use a sidebar para iniciar um monitoramento.")
        return
    opportunity_df = df[~df["oportunidade"].isin(["normal", "Normal"])].copy()
    if opportunity_df.empty:
        st.info("Nenhuma oportunidade classificada como boa, ótima ou excelente até agora.")
        return
    opportunity_df["detectado_em_dt"] = safe_datetime_series(opportunity_df["detectado_em"])
    ordered = opportunity_df.sort_values(["score", "economia", "detectado_em_dt"], ascending=[False, False, False]).head(12)

    for start in range(0, len(ordered), 3):
        cols = st.columns(3)
        for col, (_, row) in zip(cols, ordered.iloc[start:start + 3].iterrows()):
            alert_label = "Alerta enviado" if row["alerta"] not in {"-", "failed"} and not str(row["alerta"]).startswith("failed") else "Sem alerta"
            alert_class = "tag-alert" if alert_label == "Alerta enviado" else "tag-muted"
            economy = row["economia"] if row["economia"] is not None else 0
            card_class = "opportunity-card excellent" if row["oportunidade"] in {"excelente_oportunidade", "oportunidade_rara", "Ótima oportunidade", "Excelente oportunidade"} else "opportunity-card"
            tag_class = {
                "boa_oportunidade": "tag-good",
                "excelente_oportunidade": "tag-excellent",
                "oportunidade_rara": "tag-great",
                "Boa oportunidade": "tag-good",
                "Ótima oportunidade": "tag-great",
                "Excelente oportunidade": "tag-excellent",
            }.get(row["oportunidade"], "tag-muted")

            miles = estimate_miles(float(row["preço"] or 0))
            miles_html = f'<div class="opportunity-miles">🏆 {format_miles(miles)}</div>'

            # Connection hub info
            via_hub = str(row.get("via_hub") or "")
            via_html = (
                f'<div class="opportunity-detail via-hub-tag">🔗 Conexão via {via_hub} '
                f'(combinação de trechos)</div>'
                if via_hub else ""
            )
            is_combined = bool(via_hub)
            combined_note = (
                '<div class="opportunity-detail" style="color:#FDE68A;font-size:.78rem;">'
                '⚠️ Preço soma dois trechos independentes — reserve cada trecho separadamente.'
                '</div>'
                if is_combined else ""
            )

            col.markdown(
                f"""
                <div class="{card_class}">
                    <span class="tag {tag_class}">{row['classificação']}</span>
                    <span class="tag {alert_class}">{alert_label}</span>
                    {'<span class="tag tag-connection">Via ' + via_hub + '</span>' if via_hub else ''}
                    <div class="opportunity-route">{row['rota']}</div>
                    {via_html}
                    <div class="opportunity-detail">Ida: {format_date(row['ida'])} · Volta: {format_date(row['volta'])}</div>
                    <div class="opportunity-price">{format_brl(row['preço'])}</div>
                    {miles_html}
                    <div class="opportunity-detail">Preço máximo: {money(row['preço máximo'], row['moeda'])}</div>
                    <div class="opportunity-detail">Economia estimada: {money(economy, row['moeda'])}</div>
                    <div class="opportunity-detail">Score: {row['score']}/100 · {row['companhia']}</div>
                    <div class="opportunity-detail">Provider: {row['provedor']}</div>
                    <div class="opportunity-detail">Duração: {row['duração']} · Escalas: {row['escalas']}</div>
                    {combined_note}
                    <div class="opportunity-detail"><a class="buy-link" href="{row['link']}" target="_blank">Abrir link de compra →</a></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.caption("* Milhas estimadas com base em R$ 0,035/milha. Não representa disponibilidade real em programas de fidelidade.")


# ─── Tab: Buscas Ativas ───────────────────────────────────────────────────────

def render_searches(summary: dict, df_quotes: pd.DataFrame) -> None:
    st.subheader("Buscas ativas")
    searches = summary["searches"]
    if not searches:
        st.info("Nenhuma busca cadastrada. O painel de criação fica na sidebar.")
        return
    df = searches_df(searches, df_quotes)
    display = df.copy()
    display["milhas est."] = display["menor preço encontrado"].apply(
        lambda p: format_miles(estimate_miles(float(p))) if pd.notna(p) and p else "–"
    )
    display["data de ida"] = display["data de ida"].map(format_date)
    display["data de volta"] = display["data de volta"].map(format_date)
    display["última consulta"] = display["última consulta"].map(format_datetime)
    display["preço máximo"] = display["preço máximo"].map(money)
    display["menor preço encontrado"] = display["menor preço encontrado"].map(money)
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption("* Milhas estimadas com base em R$ 0,035/milha. Não representa disponibilidade real em programas de fidelidade.")

    st.markdown("**Pausar ou reativar monitoramento**")
    for start in range(0, len(searches), 4):
        cols = st.columns(4)
        for col, search in zip(cols, searches[start:start + 4]):
            action = "Pausar" if search.is_active else "Reativar"
            label = f"{action} #{search.id} · {search.origin}→{search.destination}"
            if col.button(label, key=f"toggle-search-{search.id}", use_container_width=True):
                with session_scope() as db:
                    item = db.get(FlightSearch, search.id)
                    if item:
                        item.is_active = not item.is_active
                st.rerun()


# ─── Tab: Histórico ───────────────────────────────────────────────────────────

def render_year_price_calendar(summary: dict, df: pd.DataFrame) -> None:
    st.subheader("Melhores preços nos próximos 12 meses")
    if df.empty:
        st.info("Defina origem e destino na sidebar e clique em Buscar agora para montar o calendário anual.")
        return

    context = route_context_from_latest(summary)
    if not context:
        st.info("Defina uma rota na sidebar para ver o calendário anual de preços.")
        return

    origin = str(context.get("origin_code") or "").upper()
    destination = str(context.get("destination_code") or "").upper()
    route_df = df[(df["origem"] == origin) & (df["destino"] == destination)].copy()
    if route_df.empty:
        st.info("Ainda não há cotações salvas para esta rota. Clique em Buscar agora para coletar o calendário anual.")
        return

    route_df["ida_dt"] = pd.to_datetime(route_df["ida"], errors="coerce")
    today = pd.Timestamp(date.today())
    one_year = today + pd.Timedelta(days=365)
    route_df = route_df[(route_df["ida_dt"] >= today) & (route_df["ida_dt"] <= one_year)]
    route_df = route_df.dropna(subset=["ida_dt", "preço"])
    if route_df.empty:
        st.info("Não há cotações futuras no intervalo de 12 meses para esta rota.")
        return

    route_df["companhia"] = route_df["companhia"].fillna("Companhia não informada").replace("", "Companhia não informada")
    best_by_airline = (
        route_df.groupby(["ida_dt", "companhia"], as_index=False)
        .agg(preço=("preço", "min"), provedor=("provedor", "first"), link=("link", "first"))
        .sort_values(["ida_dt", "preço"])
    )
    best_overall = best_by_airline.loc[best_by_airline.groupby("ida_dt")["preço"].idxmin()].copy()

    cal_metrics = [
        ("Menor preço anual", money(best_overall["preço"].min()), f"{origin} → {destination}"),
        ("Preço médio anual", money(best_overall["preço"].mean()), "Menores tarifas por data"),
        ("Companhias", best_by_airline["companhia"].nunique(), "Com cotações registradas"),
        ("Datas mapeadas", best_overall["ida_dt"].nunique(), "Próximos 12 meses"),
    ]
    render_metric_cards(cal_metrics)

    fig = px.line(
        best_by_airline,
        x="ida_dt",
        y="preço",
        color="companhia",
        markers=True,
        labels={"ida_dt": "Data de ida", "preço": "Preço", "companhia": "Companhia"},
    )
    fig.add_scatter(
        x=best_overall["ida_dt"],
        y=best_overall["preço"],
        mode="markers",
        name="Melhor do dia",
        marker=dict(size=10, color="#2DD4BF", symbol="diamond"),
    )
    fig.update_layout(
        height=430,
        margin=dict(l=8, r=8, t=20, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

    table = best_overall.sort_values("preço").head(12)[["ida_dt", "companhia", "preço", "provedor", "link"]].copy()
    table["data de ida"] = table["ida_dt"].map(format_date)
    table["milhas est."] = table["preço"].apply(lambda p: format_miles(estimate_miles(float(p or 0))))
    table["preço"] = table["preço"].map(format_brl)
    table = table[["data de ida", "companhia", "preço", "milhas est.", "provedor", "link"]]
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption("* Milhas estimadas com base em R$ 0,035/milha. Não representa disponibilidade real em programas de fidelidade.")


def render_history(df: pd.DataFrame) -> None:
    st.subheader("Histórico de preços")
    if df.empty:
        st.info("Ainda não há histórico de cotações.")
        return
    routes = ["Todas"] + sorted(df["rota"].unique().tolist())
    route = st.selectbox("Filtrar por rota", routes)
    filtered = df if route == "Todas" else df[df["rota"] == route]
    hist_metrics = [
        ("Menor histórico", money(filtered["preço"].min()), "Mínimo registrado"),
        ("Preço médio", money(filtered["preço"].mean()), "Média das cotações"),
        ("Maior preço", money(filtered["preço"].max()), "Máximo registrado"),
        (
            "Variação",
            f"{(((filtered['preço'].max() - filtered['preço'].min()) / filtered['preço'].min()) * 100):.1f}%"
            if filtered["preço"].min() else "-",
            "Entre mínimo e máximo",
        ),
    ]
    render_metric_cards(hist_metrics)
    st.divider()
    chart_df = filtered.copy()
    chart_df["detectado_em_dt"] = safe_datetime_series(chart_df["detectado_em"])
    chart_df = chart_df.dropna(subset=["detectado_em_dt"])
    chart_df["detectado_em"] = chart_df["detectado_em_dt"]
    fig = px.line(chart_df.sort_values("detectado_em"), x="detectado_em", y="preço", color="rota", markers=True)
    fig.update_layout(height=420, margin=dict(l=8, r=8, t=20, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)
    table = filtered[
        ["rota", "ida", "volta", "companhia", "preço", "moeda", "provedor", "classificação", "detectado_em", "link"]
    ].copy()
    table["milhas est."] = table["preço"].apply(lambda p: format_miles(estimate_miles(float(p or 0))))
    table["ida"] = table["ida"].map(format_date)
    table["volta"] = table["volta"].map(format_date)
    table["preço"] = table["preço"].map(format_brl)
    table["detectado_em"] = table["detectado_em"].map(format_datetime)
    table = table[
        ["rota", "ida", "volta", "companhia", "preço", "milhas est.", "moeda", "provedor", "classificação", "detectado_em", "link"]
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption("* Milhas estimadas com base em R$ 0,035/milha. Não representa disponibilidade real em programas de fidelidade.")


# ─── Tab: Milhas ──────────────────────────────────────────────────────────────

def render_miles_tab(df: pd.DataFrame) -> None:
    st.subheader("Estimativa de milhas")

    st.markdown(
        '<div class="miles-disclaimer">'
        "⚠️ <strong>Aviso importante:</strong> Os valores em milhas exibidos nesta aba são <strong>estimativas</strong> "
        "calculadas com base em um valor de referência por milha (padrão: R$ 0,035). "
        "Eles <strong>não representam disponibilidade real</strong> em programas de fidelidade como "
        "Smiles, TudoAzul, Latam Pass, Livelo ou similares. "
        "Consulte o programa de fidelidade da companhia para verificar disponibilidade e resgates reais."
        "</div>",
        unsafe_allow_html=True,
    )

    cents_per_mile = st.slider(
        "Valor estimado por milha (R$)",
        min_value=0.010,
        max_value=0.100,
        value=DEFAULT_CENTS_PER_MILE,
        step=0.005,
        format="R$ %.3f",
        help="Ajuste o custo estimado por milha para recalcular as estimativas.",
    )

    st.caption(f"Fórmula: milhas = preço em R$ ÷ {cents_per_mile:.3f}".replace(".", ","))

    if df.empty:
        st.markdown(
            '<div class="dados-ausentes">📭 <strong>Dados Ausentes</strong><br>'
            '<span>Nenhuma cotação real coletada ainda. Cadastre uma busca na sidebar e '
            'aguarde o monitor coletar os preços para ver as estimativas de milhas.</span></div>',
            unsafe_allow_html=True,
        )
        return

    miles_df = df.copy()
    miles_df["estimativa_milhas"] = miles_df["preço"].apply(
        lambda p: estimate_miles(float(p or 0), cents_per_mile)
    )
    miles_df["milhas_formatadas"] = miles_df["estimativa_milhas"].apply(format_miles)
    miles_df["preço_fmt"] = miles_df["preço"].apply(format_brl)

    # Top 10 by price (cheapest = fewest miles needed)
    top = miles_df.sort_values("preço").head(10)

    m_cols = st.columns(3)
    with m_cols[0]:
        st.markdown(
            f'<div class="miles-card"><div class="miles-card-label">Menor estimativa</div>'
            f'<div class="miles-card-value">{format_miles(int(top["estimativa_milhas"].min() if not top.empty else 0))}</div></div>',
            unsafe_allow_html=True,
        )
    with m_cols[1]:
        st.markdown(
            f'<div class="miles-card"><div class="miles-card-label">Média estimada</div>'
            f'<div class="miles-card-value">{format_miles(int(top["estimativa_milhas"].mean() if not top.empty else 0))}</div></div>',
            unsafe_allow_html=True,
        )
    with m_cols[2]:
        st.markdown(
            f'<div class="miles-card"><div class="miles-card-label">Valor ref. por milha</div>'
            f'<div class="miles-card-value">R$ {cents_per_mile:.3f}</div></div>'.replace(".", ","),
            unsafe_allow_html=True,
        )

    st.write("")
    st.subheader("Comparativo: dinheiro × milhas")
    display = top[["rota", "ida", "companhia", "preço_fmt", "milhas_formatadas", "classificação", "provedor"]].copy()
    display.columns = ["Rota", "Data ida", "Companhia", "Preço R$", "Milhas estimadas", "Classificação", "Provider"]
    display["Data ida"] = display["Data ida"].map(format_date)
    st.dataframe(display, use_container_width=True, hide_index=True)


# ─── Tab: Configurações ───────────────────────────────────────────────────────

def render_settings(provider_status: dict[str, Any], db_connected: bool) -> None:
    settings = get_settings()
    st.subheader("Configurações operacionais")
    st.markdown('<p class="section-note">Valores sensíveis não são exibidos. Apenas o status de configuração aparece aqui.</p>', unsafe_allow_html=True)
    db_source = database_diagnostics().get("source")
    database_configured = db_source == "DATABASE_URL"
    provider_rows = [
        {"configuração": "DATABASE_URL", "status": "Configurado" if database_configured else "Não configurado"},
        {"configuração": "TRAVELPAYOUTS_API_TOKEN", "status": "Configurado" if settings.travelpayouts_api_token else "Não configurado"},
        {"configuração": "ENABLE_AIRLINE_SCRAPERS", "status": "Ativo" if settings.enable_airline_scrapers else "Inativo"},
        {"configuração": "TELEGRAM_BOT_TOKEN", "status": "Configurado" if settings.telegram_bot_token else "Não configurado"},
        {"configuração": "TELEGRAM_CHAT_ID", "status": "Configurado" if settings.telegram_chat_id else "Não configurado"},
        {"configuração": "Provider ativo", "status": provider_status["provider_label"]},
        {"configuração": "Modo atual", "status": "Demonstração" if provider_status["demo_mode"] else "Travelpayouts real"},
        {"configuração": "Banco", "status": "Conectado" if db_connected else "Indisponível"},
    ]
    st.dataframe(pd.DataFrame(provider_rows), use_container_width=True, hide_index=True)

    st.markdown("**Teste de conexão Travelpayouts**")
    if st.button("Testar conexão com Travelpayouts", use_container_width=True):
        provider = TravelPayoutsProvider(timeout=15)
        if not provider.is_configured():
            st.warning("TRAVELPAYOUTS_API_TOKEN nao configurado. O app continuara em modo demonstracao.")
        else:
            try:
                sample = provider.search_flights(
                    origin="GRU",
                    destination="LIS",
                    departure_date=date.today() + timedelta(days=60),
                    return_date=date.today() + timedelta(days=75),
                    currency="BRL",
                    limit=1,
                )
                if sample:
                    st.success("✅ Conexão com Travelpayouts realizada com sucesso. A API retornou cotações reais.")
                else:
                    st.info("Conexão realizada, mas a API não retornou cotações para a rota de teste.")
            except TravelPayoutsProviderError as exc:
                st.error(str(exc))

    latest_provider_log = load_summary().get("latest_provider_log")
    if latest_provider_log:
        st.markdown("**Último diagnóstico Travelpayouts**")
        st.dataframe(
            pd.DataFrame([{
                "status": latest_provider_log.status,
                "mensagem": latest_provider_log.error_message or "-",
                "registrado_em": format_datetime(latest_provider_log.created_at),
            }]),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("**Como configurar secrets**")
    st.markdown(
        "Configure os secrets no Streamlit Cloud e também em `Settings > Secrets and variables > Actions` "
        "no GitHub para o robô agendado."
    )
    st.code(
        """TRAVELPAYOUTS_API_TOKEN = "seu_token"
TELEGRAM_BOT_TOKEN = "seu_bot_token"
TELEGRAM_CHAT_ID = "seu_chat_id"
DATABASE_URL = "postgresql://user:pass@host/db" """,
        language="toml",
    )
    st.markdown("**Diagnóstico do banco**")
    st.json(database_diagnostics())


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    require_password()
    provider_status = get_provider_status(get_settings())
    db_connected = True
    try:
        init_db()
        seed_if_empty(enable_demo_seed=False)
    except Exception as exc:  # noqa: BLE001
        db_connected = False
        load_custom_css()
        st.error("Não foi possível iniciar o banco de dados.")
        st.write("Confira se o secret `DATABASE_URL` está configurado corretamente no Streamlit Cloud.")
        st.json(database_diagnostics())
        st.code(str(exc), language="text")
        st.stop()

    summary = load_summary()
    render_sidebar(summary, provider_status, db_connected)
    render_header(provider_status, summary.get("latest_provider_log"))

    df_quotes = quotes_df(summary["quotes"], summary["searches"], summary["latest_alert_by_quote"])
    real_df_quotes = filter_real_quotes_df(df_quotes)

    (
        tab_home,
        tab_opportunities,
        tab_searches,
        tab_history,
        tab_miles,
        tab_settings,
    ) = st.tabs(["🏠 Início", "🎯 Oportunidades", "🛰️ Buscas Ativas", "📈 Histórico", "🏆 Milhas", "⚙️ Configurações"])

    with tab_home:
        render_home_tab(summary, real_df_quotes, provider_status)

    with tab_opportunities:
        render_opportunities(real_df_quotes)

    with tab_searches:
        render_searches(summary, real_df_quotes)

    with tab_history:
        render_year_price_calendar(summary, real_df_quotes)
        st.divider()
        render_history(real_df_quotes)

    with tab_miles:
        render_miles_tab(real_df_quotes)

    with tab_settings:
        render_settings(provider_status, db_connected)


if __name__ == "__main__":
    main()
