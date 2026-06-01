from __future__ import annotations

import json
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
from services.database_service import save_best_deals
from app.settings import get_settings
from app.styles import load_custom_css
from components.cards import render_airline_comparison, render_deal_cards_section, render_origin_card
from components.airport_cards import render_airport_cards
from components.fare_cards import render_fare_cards, render_fare_variants
from components.charts import render_current_prices_bar, render_future_projection
from components.monitor_prompt import render_monitor_prompt
from components.decision_cards import (
    render_decision_summary,
    render_opportunity_cards,
    render_radar_overview,
    render_search_summary,
)
from components.progress import render_execution_progress
from data.airlines_catalog import get_airline_name
from data.destinations_catalog import BRAZIL_IATAS, DESTINATIONS, get_destination_info
from data.geography_catalog import (
    AREA_BOTH,
    AREA_BRAZIL,
    AREA_INTERNATIONAL,
    BRAZIL_REGIONS,
    INTERNATIONAL_REGIONS,
)
from services.geography_filter_service import (
    describe_filters,
    get_destination_iatas_for_filters,
    scope_for_area,
)
from services.decision_engine import build_purchase_recommendation
from services.multi_destination_adapter import (
    find_cheapest_destinations,
    live_multi_destination_search,
)
from providers.travelpayouts_provider import TravelPayoutsProvider, TravelPayoutsProviderError
from services.air_network import find_candidate_hubs, hub_route_label
from services.github_actions_service import is_configured as github_trigger_configured, trigger_monitor
from services.miles_service import DEFAULT_CENTS_PER_MILE, MILES_DISCLAIMER, estimate_miles, format_miles
from services.opportunity_service import (
    get_airline_comparison,
    get_best_miles_deal,
    get_home_deals,
    get_international_lowest,
    get_national_lowest,
    select_fare_variants,
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

# Search strategy (sidebar "Tipo de busca").
SEARCH_MODE_ROUTE = "Rota específica"
SEARCH_MODE_MULTI = "Encontrar destinos mais baratos"

# Scope filter for the multi-destination mode.
SCOPE_OPTIONS = {"Ambos": "ambos", "Brasil": "nacional", "Exterior": "internacional"}

# Flexible travel window (multi-destination mode): label → days ahead.
TRAVEL_WINDOW_OPTIONS = {
    "Próximos 30 dias": 30,
    "Próximos 60 dias": 60,
    "Próximos 90 dias": 90,
    "Próximos 180 dias": 180,
    "Próximo ano": 365,
}


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

def _data_version() -> int:
    """Monotonic token bumped whenever the user writes new quotes/searches. Used
    as the cache key so the dashboard refreshes immediately after a search/run."""
    return int(st.session_state.get("data_version", 0))


def bump_data_version() -> None:
    st.session_state["data_version"] = _data_version() + 1


def load_summary() -> dict:
    """Lightweight dashboard metadata (counts, searches, latest logs).

    Deliberately does NOT fetch the bulk quote rows — those are loaded and shaped
    once per window by the cached ``load_quotes_df`` so typing in the sidebar
    autocomplete (which reruns the whole script per keystroke) stays fast."""
    with session_scope() as db:
        active = db.scalar(select(func.count()).select_from(FlightSearch).where(FlightSearch.is_active.is_(True))) or 0
        alerts = db.scalar(select(func.count()).select_from(AlertLog)) or 0
        searches = list(db.scalars(select(FlightSearch).order_by(FlightSearch.created_at.desc())))
        latest_search = db.scalar(select(func.max(FlightSearch.last_checked_at)))
        latest_provider_log = db.scalar(
            select(ProviderLog)
            .where(ProviderLog.provider == "travelpayouts")
            .order_by(ProviderLog.created_at.desc())
            .limit(1)
        )
        routes = len({f"{search.origin}-{search.destination}" for search in searches})
    return {
        "active": active,
        "alerts": alerts,
        "searches": searches,
        "latest_search": latest_search,
        "latest_provider_log": latest_provider_log,
        "routes": routes,
    }


@st.cache_data(ttl=90, show_spinner=False)
def load_quotes_df(data_version: int) -> pd.DataFrame:
    """Fetch the recent quotes and build the working DataFrame — the expensive
    step. Cached (90s TTL, keyed by ``data_version``) so it runs at most once per
    window instead of on every keystroke. ``bump_data_version`` forces a refresh
    right after the user runs a search."""
    with session_scope() as db:
        quotes = list(db.scalars(select(FlightQuote).order_by(FlightQuote.detected_at.desc()).limit(5000)))
        searches = list(db.scalars(select(FlightSearch)))
        alerts_by_quote = {
            quote_id: status
            for quote_id, status in db.execute(
                select(AlertLog.quote_id, AlertLog.status).where(AlertLog.quote_id.is_not(None))
            )
        }
    return quotes_df(quotes, searches, alerts_by_quote)


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
                "companhia": get_airline_name(quote.airline),
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
    # No `help=` here on purpose: the "?" tooltip caused an unwanted floating
    # history/hint over the Origem/Destino fields. Labels are kept clean.
    query = st.text_input(
        label,
        value="",
        key=f"{key}_query",
        placeholder="Cidade, país ou código do aeroporto",
    ).strip()
    if not query:
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


# ─── Multi-destination search ─────────────────────────────────────────────────

def _run_multi_destination_search(
    origin_location,
    *,
    area_scope: str,
    brazil_regions: list[str],
    international_regions: list[str],
    window_days: int,
    max_price: float,
    currency: str,
    consider_miles: bool,
    min_mile_value: float,
    start_monitoring: bool,
) -> None:
    """Run the preserved per-route engine across many destinations (live sweep).

    The geographic filter (``services.geography_filter_service``) resolves the
    selected regions into the candidate destination list; the search engine
    itself is unchanged — it just receives a narrower set of destinations.
    Stores ranked opportunities + the applied filters for the Home tab."""
    origin_code = origin_location.code
    departure = date.today() + timedelta(days=min(window_days, 60))
    params = {
        "departure_date": departure,
        "return_date": None,
        "currency": currency,
        "max_price": max_price,
        "consider_miles": consider_miles,
        "user_min_mile_value": min_mile_value,
        "adults": 1,
    }
    candidates = get_destination_iatas_for_filters(
        area_scope, brazil_regions, international_regions, origin=origin_code
    )

    if not candidates:
        st.session_state["multi_results"] = {"national": [], "international": []}
        st.session_state["multi_context"] = {
            "origin_code": origin_code, "origin_label": origin_location.label,
            "area_scope": area_scope, "brazil_regions": brazil_regions,
            "international_regions": international_regions, "candidate_count": 0,
            "scope": scope_for_area(area_scope), "min_mile_value": min_mile_value,
            "max_price": max_price,
        }
        st.session_state["last_search_feedback"] = {
            "text": "Nenhum destino elegível encontrado para os filtros selecionados.",
            "level": "warning",
        }
        return

    opportunities = live_multi_destination_search(
        origin_code, candidates, params, max_destinations=16, min_mile_value=min_mile_value
    )

    # Register a multi-destination monitor entry (destination = ANYWHERE) so the
    # search shows up in "Buscas ativas" and the scheduled monitor can refresh it.
    # Persist the applied geo filters on it and the ranked opportunities.
    try:
        with session_scope() as db:
            db.add(
                FlightSearch(
                    owner_email="demo@radar.local",
                    origin=origin_code,
                    destination="ANYWHERE",
                    departure_date=departure,
                    return_date=None,
                    adults=1,
                    passengers=1,
                    max_price=float(max_price),
                    currency=currency,
                    trip_type="one_way",
                    frequency_minutes=60,
                    is_active=bool(start_monitoring),
                    area_scope=area_scope,
                    brazil_regions=json.dumps(brazil_regions, ensure_ascii=False),
                    international_regions=json.dumps(international_regions, ensure_ascii=False),
                    candidate_destinations=json.dumps(candidates, ensure_ascii=False),
                )
            )
            save_best_deals(db, origin_code, opportunities)
    except Exception:
        pass

    national = [o for o in opportunities if o["destination_type"] == "national"]
    international = [o for o in opportunities if o["destination_type"] == "international"]
    st.session_state["multi_results"] = {
        "national": national,
        "international": international,
    }
    st.session_state["multi_context"] = {
        "origin_code": origin_code,
        "origin_label": origin_location.label,
        "scope": scope_for_area(area_scope),
        "area_scope": area_scope,
        "brazil_regions": brazil_regions,
        "international_regions": international_regions,
        "candidate_count": len(candidates),
        "window_days": window_days,
        "consider_miles": consider_miles,
        "min_mile_value": min_mile_value,
        "max_price": max_price,
    }
    found = len(opportunities)
    verb = "Monitorando" if start_monitoring else "Encontrados"
    st.session_state["last_search_feedback"] = {
        "text": f"✅ {verb} {found} destino(s) entre {len(candidates)} aeroportos no radar.",
        "level": "success",
    }
    bump_data_version()  # refresh the cached quotes dataframe


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
        # ── Estratégia de busca ────────────────────────────────────────────
        search_mode = st.radio(
            "Tipo de busca",
            [SEARCH_MODE_ROUTE, SEARCH_MODE_MULTI],
            key="search_mode",
            help="Rota específica: compara companhias para um destino. "
            "Encontrar destinos mais baratos: usa o motor de múltiplos destinos.",
        )
        is_multi = search_mode == SEARCH_MODE_MULTI

        origin_input, selected_origin = _render_location_picker("Origem", "origin")
        # Destino só aparece no modo "Rota específica".
        if not is_multi:
            destination_input, selected_destination = _render_location_picker("Destino", "destination")
        else:
            destination_input, selected_destination = "", None

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

        # ── Filtros geográficos (fora do form para reagir na hora) ──────────
        area_scope = AREA_BOTH
        brazil_regions: list[str] = []
        international_regions: list[str] = []
        if is_multi:
            area_scope = st.radio(
                "Área da busca",
                [AREA_BRAZIL, AREA_INTERNATIONAL, AREA_BOTH],
                index=2,
                horizontal=True,
                key="multi_area_scope",
                help="Refine onde o radar procura os destinos mais baratos.",
            )
            if area_scope in (AREA_BRAZIL, AREA_BOTH):
                brazil_regions = st.multiselect(
                    "Regiões do Brasil",
                    list(BRAZIL_REGIONS.keys()),
                    key="multi_brazil_regions",
                    help="Vazio = todas as regiões do Brasil.",
                )
            if area_scope in (AREA_INTERNATIONAL, AREA_BOTH):
                international_regions = st.multiselect(
                    "Continentes/regiões internacionais",
                    list(INTERNATIONAL_REGIONS.keys()),
                    key="multi_intl_regions",
                    help="Vazio = todas as regiões internacionais.",
                )

        with st.form("new_search_form", clear_on_submit=False):
            if is_multi:
                # Multiple-destination mode: flexible window instead of a single
                # destination/date. Geographic filters are chosen above the form.
                travel_window_label = st.selectbox(
                    "Janela de viagem", list(TRAVEL_WINDOW_OPTIONS.keys()), index=2
                )
                departure = None
                trip_label = "ida e volta"
                return_date = None
                flexibility = "mês inteiro"
            else:
                travel_window_label = None
                departure = st.date_input("Data de ida", value=None, format="DD/MM/YYYY")
                trip_label = st.selectbox("Tipo de viagem", list(TRIP_TYPE_OPTIONS.keys()), index=1)
                return_date = st.date_input(
                    "Data de volta",
                    value=None,
                    disabled=TRIP_TYPE_OPTIONS[trip_label] == "one_way",
                    format="DD/MM/YYYY",
                )
                flexibility = st.selectbox("Flexibilidade de datas", list(FLEXIBILITY_OPTIONS.keys()))

            max_price = st.number_input("Preço máximo (R$)", min_value=100.0, value=3200.0, step=50.0)
            currency = st.selectbox("Moeda", ["BRL", "USD", "EUR"], index=0)
            consider_miles = st.toggle("Considerar milhas", value=True)
            telegram_enabled = st.toggle(
                "Alertas via Telegram",
                value=bool(settings.telegram_bot_token and settings.telegram_chat_id),
            )

            search_now = st.form_submit_button("🔍 Buscar agora", type="primary", use_container_width=True)
            # "Iniciar monitoramento" saiu da sidebar: o monitoramento agora é
            # oferecido na área principal, após uma busca bem-sucedida
            # (botão "Monitorar esta rota 24h").
            start_monitoring = False

        # Internal defaults for fields removed from the sidebar (kept in state so
        # the rest of the flow and the worker keep working unchanged).
        adults = 1
        frequency_label_selected = "1h"          # FREQUENCY_OPTIONS["1h"] == 60
        min_mile_value = float(DEFAULT_CENTS_PER_MILE)  # 0.035

        # Expose the decision/miles preferences to the Home tab (read on rerun).
        st.session_state["radar_prefs"] = {
            "consider_miles": bool(consider_miles),
            "min_mile_value": float(min_mile_value),
            "max_price": float(max_price),
            "scope": scope_for_area(area_scope),
            "area_scope": area_scope,
            "brazil_regions": list(brazil_regions),
            "international_regions": list(international_regions),
            "travel_window_days": TRAVEL_WINDOW_OPTIONS.get(travel_window_label or "", 90),
        }

        if (search_now or start_monitoring) and is_multi:
            # ── Multiple-destination sweep (preserved engine via adapter) ──────
            origin_location = selected_origin or _resolve_search_location(origin_input, "a origem")
            if not origin_location:
                st.warning("Informe a origem para buscar destinos mais baratos.")
            else:
                _run_multi_destination_search(
                    origin_location,
                    area_scope=area_scope,
                    brazil_regions=list(brazil_regions),
                    international_regions=list(international_regions),
                    window_days=TRAVEL_WINDOW_OPTIONS.get(travel_window_label or "", 90),
                    max_price=float(max_price),
                    currency=currency,
                    consider_miles=bool(consider_miles),
                    min_mile_value=float(min_mile_value),
                    start_monitoring=bool(start_monitoring),
                )
                st.rerun()

        elif search_now or start_monitoring:
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
                # ── Busca IMEDIATA via API (não depende do GitHub Actions) ─────
                import time as _time
                t_start = _time.monotonic()
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
                        search_type="route",
                        telegram_enabled=bool(telegram_enabled),
                        consider_miles=bool(consider_miles),
                        min_mile_value=float(min_mile_value),
                    )
                    db.add(search)
                    db.flush()
                    with st.spinner("Consultando a API agora… (resultado imediato)"):
                        saved = run_search_once(db, search, include_year_calendar=True)
                api_seconds = _time.monotonic() - t_start
                if start_monitoring:
                    save_msg = f"🛰️ Monitoramento iniciado. Busca imediata via API salvou {saved} cotação(ões)."
                else:
                    save_msg = f"✅ Busca imediata via API concluída em {api_seconds:.1f}s — {saved} cotação(ões) salvas."

                # ── Execução COMPLEMENTAR no GitHub Actions/worker (mais lenta) ──
                # Não bloqueia a interface: a busca acima já retornou. O worker faz
                # o scraping completo e segue monitorando.
                t_trigger = _time.monotonic()
                trigger_msg = None
                trigger_level = "info"
                worker_status = "not_configured"
                if github_trigger_configured():
                    dispatch = trigger_monitor(force=True)
                    if dispatch.ok:
                        worker_status = "queued"
                        trigger_msg = (
                            "🚀 " + dispatch.message + " A API já trouxe os preços acima; "
                            "o GitHub Actions roda em paralelo e pode levar alguns minutos."
                        )
                        trigger_level = "info"
                    else:
                        worker_status = "failed"
                        trigger_msg = "⚠️ " + dispatch.message
                        trigger_level = "warning"
                else:
                    trigger_msg = (
                        "ℹ️ Resultados imediatos vêm da API. Para o scraping complementar via "
                        "GitHub Actions, configure GITHUB_TOKEN e GITHUB_REPO."
                    )
                    trigger_level = "caption"
                trigger_seconds = _time.monotonic() - t_trigger

                # Store the execution progress for the "Andamento da execução" panel.
                st.session_state["search_progress"] = {
                    "route": f"{origin_location.code.upper()} → {destination_location.code.upper()}",
                    "origin_code": origin_location.code.upper(),
                    "destination_code": destination_location.code.upper(),
                    "api_seconds": round(api_seconds, 1),
                    "trigger_seconds": round(trigger_seconds, 1),
                    "worker_status": worker_status,
                    "worker_estimate_seconds": 90,
                    "saved": saved,
                    "started_at": _time.time(),
                    "mode": "route",
                }

                # Persist feedback across the rerun below (messages set here would
                # otherwise be wiped by st.rerun()).
                st.session_state["last_search_feedback"] = {"text": save_msg, "level": "success"}
                st.session_state["last_trigger_feedback"] = {"text": trigger_msg, "level": trigger_level}
                bump_data_version()  # refresh the cached quotes dataframe
                st.rerun()

        st.divider()

        # (O "Status do sistema" saiu da sidebar para deixá-la mais limpa — ele
        # continua disponível na aba Configurações.)

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


def _recent_history_for_route(df_quotes: pd.DataFrame, origin: str, dest: str) -> dict:
    """Short recent stats (min/avg) for a route — supporting evidence only.

    Reads the existing quote history; never used as the protagonist on screen,
    only fed to the decision engine to phrase 'X% abaixo da média recente'."""
    if df_quotes is None or df_quotes.empty or "preço" not in df_quotes.columns:
        return {}
    sub = df_quotes[
        (df_quotes["origem"].astype(str).str.upper() == origin)
        & (df_quotes["destino"].astype(str).str.upper() == dest)
        & (df_quotes["preço"] > 0)
    ]
    if sub.empty:
        return {}
    return {
        "recent_min": float(sub["preço"].min()),
        "recent_avg": float(sub["preço"].mean()),
        "sample_size": int(len(sub)),
    }


def _radar_overview_metrics(summary: dict, df_quotes: pd.DataFrame, prefs: dict) -> dict:
    """Compute the 'Radar de decisão' KPI strip from collected data."""
    cents = float(prefs.get("min_mile_value") or DEFAULT_CENTS_PER_MILE)
    nat_low = get_national_lowest(df_quotes)
    intl_low = get_international_lowest(df_quotes)
    best_miles = get_best_miles_deal(df_quotes, cents)

    best_cash_val = None
    candidates = [v for v in (nat_low, intl_low) if v]
    if candidates:
        best_cash_val = min(candidates)

    return {
        "best_cash": format_brl(best_cash_val) if best_cash_val else "Sem dados",
        "best_cash_sub": "Menor preço atual coletado" if best_cash_val else "Faça uma busca",
        "best_miles": format_miles(int(best_miles.get("estimated_miles"))) if best_miles else "Sem dados",
        "best_miles_sub": "Estimativa do voo mais barato" if best_miles else "—",
        "best_national": format_brl(nat_low) if nat_low else "Sem dados",
        "best_national_sub": "Voo nacional mais barato",
        "best_international": format_brl(intl_low) if intl_low else "Sem dados",
        "best_international_sub": "Voo internacional mais barato",
        "monitor": str(summary.get("active", 0)),
        "monitor_sub": "Rotas em monitoramento 24h",
    }


def render_home_tab(summary: dict, df_quotes: pd.DataFrame, provider_status: dict) -> None:
    """Home screen = radar de decisão. Two modes driven by the sidebar:
    'Rota específica' (compare a route) and 'Encontrar destinos mais baratos'
    (preserved multi-destination engine)."""
    mode = st.session_state.get("search_mode", SEARCH_MODE_ROUTE)
    prefs = st.session_state.get("radar_prefs", {})
    if mode == SEARCH_MODE_MULTI:
        _render_home_multi(summary, df_quotes, prefs)
    else:
        _render_home_route(summary, df_quotes, provider_status, prefs)


def _render_home_route(summary: dict, df_quotes: pd.DataFrame, provider_status: dict, prefs: dict) -> None:
    origin = st.session_state.get("home_origin") or {}
    destination = st.session_state.get("home_destination") or {}
    origin_code = str(origin.get("code") or "").upper()
    dest_code = str(destination.get("code") or "").upper()

    consider_miles = bool(prefs.get("consider_miles", True))
    min_mile_value = float(prefs.get("min_mile_value") or DEFAULT_CENTS_PER_MILE)
    max_price = prefs.get("max_price")

    if not origin_code:
        _empty_state("🧭 Escolha origem, destino e datas na lateral. "
                     "Depois clique em <strong>Buscar agora</strong>.")
        return

    render_airport_cards(origin_code, dest_code or None)

    if not dest_code:
        _empty_state("📍 Agora escolha o destino. Depois clique em <strong>Buscar agora</strong>.")
        return

    # Results appear ONLY after the user explicitly clicked "Buscar agora" for
    # THIS route in this session (search_progress is set only in the submit
    # handler). Selecting origin/destination never triggers a search.
    progress = st.session_state.get("search_progress")
    executed = bool(
        progress
        and progress.get("origin_code") == origin_code
        and progress.get("destination_code") == dest_code
    )
    if not executed:
        _empty_state("🔍 Tudo pronto. Clique em <strong>Buscar agora</strong> "
                     "para consultar as melhores tarifas desta rota.")
        return

    last_ctx = st.session_state.get("last_route_context") or {}
    # Most recent fares for the route (no time-window filter — we always show the
    # latest available quote, not collection history).
    deals = get_airline_comparison(df_quotes, origin_code, dest_code)

    if not deals:
        _empty_state("📭 A busca foi executada, mas ainda não há tarifas reais para esta rota. "
                     "Tente novamente em alguns instantes ou ajuste as datas.")
        st.divider()
        render_monitor_prompt(_home_route_dict(origin_code, dest_code, last_ctx))
        return

    # ── Decision: the protagonist of the screen ───────────────────────────────
    recent = _recent_history_for_route(df_quotes, origin_code, dest_code)
    rec = build_purchase_recommendation(
        deals,
        {
            "max_price": max_price,
            "consider_miles": consider_miles,
            "user_min_mile_value": min_mile_value,
            "departure_date": last_ctx.get("departure_date"),
        },
        recent_history=recent,
    )

    # Search resumo card (route, cheapest, miles, airlines found, worker status).
    render_search_summary(deals, rec, route=f"{origin_code} → {dest_code}", progress=progress)

    # Execution progress: immediate API vs complementary GitHub Actions worker.
    st.divider()
    render_execution_progress(progress)

    # "Opções encontradas": at least 3 diversified fare variants.
    st.divider()
    variants = select_fare_variants(deals, max_variants=3)
    render_fare_variants(variants)

    st.divider()
    render_decision_summary(rec, consider_miles=consider_miles)

    if deals:
        st.divider()
        render_current_prices_bar(deals)

    # "Monitorar esta rota 24h" — offered in the main area as a result of the search.
    st.divider()
    render_monitor_prompt(_home_route_dict(origin_code, dest_code, last_ctx))


def _render_home_multi(summary: dict, df_quotes: pd.DataFrame, prefs: dict) -> None:
    origin = st.session_state.get("home_origin") or {}
    origin_code = str(origin.get("code") or "").upper()
    scope = prefs.get("scope", "ambos")
    area_scope = prefs.get("area_scope", AREA_BOTH)
    brazil_regions = prefs.get("brazil_regions") or []
    international_regions = prefs.get("international_regions") or []
    min_mile_value = float(prefs.get("min_mile_value") or DEFAULT_CENTS_PER_MILE)
    max_price = prefs.get("max_price")

    if not origin_code:
        _empty_state("🧭 Escolha uma origem na lateral (e regiões, se quiser). "
                     "Depois clique em <strong>Buscar agora</strong>.")
        return

    render_airport_cards(origin_code, None)

    # Results appear ONLY after an explicit multi-destination search for this
    # origin (multi_results/multi_context are set only in the submit handler).
    results = st.session_state.get("multi_results")
    ctx = st.session_state.get("multi_context") or {}
    same_origin = str(ctx.get("origin_code") or "").upper() == origin_code
    if not (results and same_origin):
        _empty_state("🔍 Tudo pronto. Clique em <strong>Buscar agora</strong> para varrer "
                     "os destinos mais baratos a partir desta origem.")
        return

    # Global decision radar overview (melhor preço / destino / milhas).
    render_radar_overview(_radar_overview_metrics(summary, df_quotes, prefs))

    # Applied-filter summary + eligible-airport count.
    candidates = get_destination_iatas_for_filters(
        area_scope, brazil_regions, international_regions, origin=origin_code
    )
    st.markdown(
        f'<div class="filter-summary">🧭 {describe_filters(area_scope, brazil_regions, international_regions)}'
        f'<span class="filter-count">{len(candidates)} aeroportos no radar.</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="deals-section-header">🧳 Destinos mais baratos encontrados</div>',
                unsafe_allow_html=True)

    if scope in {"ambos", "nacional"}:
        render_opportunity_cards(
            results.get("national", []), title="🇧🇷 Brasil",
            key_prefix="multi_nat", on_monitor=_monitor_destination,
        )
    if scope in {"ambos", "internacional"}:
        render_opportunity_cards(
            results.get("international", []), title="🌎 Exterior",
            key_prefix="multi_intl", on_monitor=_monitor_destination,
        )
    st.caption(f"ℹ️ {MILES_DISCLAIMER}")


def _monitor_destination(opp: dict) -> None:
    """Persist a 'Monitorar este destino' click as an active search."""
    try:
        with session_scope() as db:
            db.add(
                FlightSearch(
                    owner_email="demo@radar.local",
                    origin=str(opp.get("origin_iata") or "").upper(),
                    destination=str(opp.get("destination_iata") or "").upper(),
                    departure_date=opp.get("departure_date") or (date.today() + timedelta(days=45)),
                    return_date=opp.get("return_date"),
                    adults=1,
                    passengers=1,
                    max_price=float(opp.get("cash_price") or 3200.0),
                    currency="BRL",
                    trip_type="one_way",
                    frequency_minutes=60,
                    is_active=True,
                )
            )
        st.session_state["last_search_feedback"] = {
            "text": f"🛰️ Monitorando {opp.get('origin_iata')} → {opp.get('destination_iata')} 24h.",
            "level": "success",
        }
    except Exception as exc:  # pragma: no cover
        st.session_state["last_search_feedback"] = {"text": f"Erro ao monitorar: {exc}", "level": "warning"}
    st.rerun()


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

_STATUS_BADGE = {
    "active": ("🟢", "Ativa"),
    "paused": ("⏸️", "Pausada"),
    "deleted": ("🗑️", "Deletada"),
    "error": ("🔴", "Erro"),
    "completed": ("✅", "Concluída"),
}

_CTRL_FREQ_OPTIONS = {"30 minutos": 30, "1 hora": 60, "3 horas": 180, "6 horas": 360, "12 horas": 720, "24 horas": 1440}


def _ctrl_status_label(snap) -> str:
    emoji, label = _STATUS_BADGE.get(snap.status, ("•", snap.status or "—"))
    if snap.expired and snap.status == "active":
        return f"{emoji} {label} · ⌛ expirada"
    if (snap.last_status or "") == "error" and snap.status == "active":
        return f"🔴 Ativa (último erro)"
    return f"{emoji} {label}"


def _ctrl_next_run(snap) -> str:
    if snap.status != "active":
        return "—"
    if snap.last_run_at is None:
        return "Na próxima rodada"
    return format_datetime(snap.next_run_at) if snap.next_run_at else "Na próxima rodada"


def _ctrl_type_label(snap) -> str:
    return "Destinos mais baratos" if (snap.search_type == "multi" or str(snap.destination).upper() == "ANYWHERE") else "Rota específica"


def _ctrl_geo_summary(snap) -> str:
    if _ctrl_type_label(snap) != "Destinos mais baratos":
        return "—"
    try:
        br = json.loads(snap.brazil_regions or "[]")
        intl = json.loads(snap.international_regions or "[]")
    except Exception:
        br, intl = [], []
    parts = []
    if snap.area_scope:
        parts.append(snap.area_scope)
    regions = (br or []) + (intl or [])
    if regions:
        parts.append(", ".join(regions))
    return " · ".join(parts) if parts else (snap.area_scope or "Todas as regiões")


def render_search_control(summary: dict, df_quotes: pd.DataFrame) -> None:
    """Operational panel for the scheduled searches the worker will execute."""
    from services.search_control_service import (
        alert_counts,
        alerts_for_search,
        delete_search,
        duplicate_search,
        get_action_logs,
        get_run_logs,
        latest_quotes_for_search,
        list_searches,
        pause_search,
        resume_search,
        run_now,
        set_frequency,
        set_telegram,
    )

    st.subheader("🛰️ Controle de Buscas")
    st.caption("Painel operacional das buscas programadas. O GitHub Actions/worker executa "
               "apenas buscas **ativas** e não expiradas.")

    fb = st.session_state.pop("ctrl_feedback", None)
    if fb:
        getattr(st, fb.get("level", "info"))(fb["text"])

    searches = list_searches()
    counts = alert_counts()

    # ── Summary cards ─────────────────────────────────────────────────────────
    n_active = sum(1 for s in searches if s.status == "active" and not s.expired)
    n_paused = sum(1 for s in searches if s.status == "paused")
    n_error = sum(1 for s in searches if (s.last_status or "") == "error" and s.status == "active")
    total_alerts = summary.get("alerts", sum(counts.values()))
    last_worker = format_datetime(summary.get("latest_search"))
    next_runs = [s.next_run_at for s in searches if s.status == "active" and s.next_run_at]
    if any(s.status == "active" and s.last_run_at is None for s in searches):
        next_prev = "Na próxima rodada"
    elif next_runs:
        next_prev = format_datetime(min(next_runs))
    else:
        next_prev = "—"

    cards = [
        ("🟢 Buscas ativas", n_active, "rec"),
        ("⏸️ Buscas pausadas", n_paused, "mon"),
        ("🔴 Buscas com erro", n_error, "rec"),
        ("📨 Alertas enviados", total_alerts, "miles"),
        ("🕒 Última execução", last_worker, "mon"),
        ("⏭️ Próxima prevista", next_prev, "rec"),
    ]
    html = ['<div class="radar-overview-grid">']
    for label, value, mod in cards:
        html.append(
            f'<div class="radar-card radar-{mod}"><div class="radar-card-label">{label}</div>'
            f'<div class="radar-card-value">{value}</div></div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    if not searches:
        st.info("Nenhuma busca programada ainda. Crie uma na lateral com **Buscar agora** "
                "ou **Iniciar monitoramento**.")
        return

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("🔎 Filtros", expanded=False):
        fc = st.columns(4)
        f_status = fc[0].multiselect("Status", ["active", "paused", "error", "completed"], default=[])
        f_type = fc[1].multiselect("Tipo", ["Rota específica", "Destinos mais baratos"], default=[])
        f_origin = fc[2].text_input("Origem contém", "").upper().strip()
        f_telegram = fc[3].selectbox("Telegram", ["Todos", "Ativo", "Inativo"], index=0)

    def _keep(s) -> bool:
        eff_status = "error" if (s.last_status == "error" and s.status == "active") else s.status
        if f_status and eff_status not in f_status:
            return False
        if f_type and _ctrl_type_label(s) not in f_type:
            return False
        if f_origin and f_origin not in str(s.origin or "").upper():
            return False
        if f_telegram == "Ativo" and not s.telegram_enabled:
            return False
        if f_telegram == "Inativo" and s.telegram_enabled:
            return False
        return True

    filtered = [s for s in searches if _keep(s)]
    if not filtered:
        st.info("Nenhuma busca corresponde aos filtros selecionados.")
        return

    # ── Main table ────────────────────────────────────────────────────────────
    best_by_search = {}
    if not df_quotes.empty and "search_id" in df_quotes.columns and "preço" in df_quotes.columns:
        best_by_search = df_quotes.dropna(subset=["preço"]).groupby("search_id")["preço"].min().to_dict()

    table_rows = []
    for s in filtered:
        table_rows.append({
            "ID": s.id,
            "Status": _ctrl_status_label(s),
            "Tipo": _ctrl_type_label(s),
            "Origem": s.origin,
            "Destino": "—" if _ctrl_type_label(s) != "Rota específica" else s.destination,
            "Filtros geográficos": _ctrl_geo_summary(s),
            "Ida": format_date(s.departure_date),
            "Volta": format_date(s.return_date) if s.return_date else "—",
            "Preço máx.": money(s.max_price),
            "Milhas": "Sim" if s.consider_miles else "Não",
            "Freq.": frequency_label(s.frequency_minutes),
            "Telegram": "✅" if s.telegram_enabled else "—",
            "Última exec.": format_datetime(s.last_run_at) if s.last_run_at else "—",
            "Próxima exec.": _ctrl_next_run(s),
            "Menor preço": money(best_by_search.get(s.id)) if best_by_search.get(s.id) else "—",
            "Alertas": counts.get(s.id, 0),
            "Criada": format_date(s.created_at),
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    st.caption("O worker executa apenas buscas com status **Ativa** e data não expirada.")

    # ── Selected-search action panel ──────────────────────────────────────────
    st.markdown("### Ações da busca selecionada")
    id_options = [s.id for s in filtered]
    snap_by_id = {s.id: s for s in filtered}
    selected_id = st.selectbox(
        "Selecionar busca (ID)", id_options,
        format_func=lambda i: f"#{i} · {snap_by_id[i].origin}→{snap_by_id[i].destination} ({_ctrl_status_label(snap_by_id[i])})",
    )
    sel = snap_by_id[selected_id]

    # Resumo
    rec_last = next((r.get("recommendation") for r in get_run_logs(selected_id, 5) if r.get("recommendation")), None)
    resumo = [
        ("Rota / filtros", f"{sel.origin} → {sel.destination}" if _ctrl_type_label(sel) == "Rota específica"
            else f"{sel.origin} → {_ctrl_geo_summary(sel)}"),
        ("Status", _ctrl_status_label(sel)),
        ("Frequência", frequency_label(sel.frequency_minutes)),
        ("Última execução", format_datetime(sel.last_run_at) if sel.last_run_at else "Nunca"),
        ("Próxima execução", _ctrl_next_run(sel)),
        ("Telegram", "Ativo" if sel.telegram_enabled else "Inativo"),
        ("Preço máximo", money(sel.max_price)),
        ("Milhas", f"Sim (mín. R$ {sel.min_mile_value:.3f})".replace(".", ",") if sel.consider_miles else "Não"),
        ("Menor preço", money(best_by_search.get(sel.id)) if best_by_search.get(sel.id) else "—"),
        ("Última recomendação", rec_last or "—"),
    ]
    rcols = st.columns(2)
    for i, (label, value) in enumerate(resumo):
        rcols[i % 2].markdown(
            f'<div class="status-row"><span class="status-label">{label}</span>'
            f'<span class="status-value">{value}</span></div>', unsafe_allow_html=True)

    if sel.last_status == "error" and sel.last_error:
        st.warning(f"Último erro: {sel.last_error}")
    if sel.expired:
        st.info("⌛ Esta busca está expirada (data de ida no passado). O worker a ignora. "
                "Você pode deletá-la ou duplicá-la com novas datas.")

    # Action buttons
    b = st.columns(4)
    if b[0].button("⏸️ Pausar", key="ctrl_pause", use_container_width=True, disabled=sel.status != "active"):
        pause_search(selected_id)
        st.session_state["ctrl_feedback"] = {"level": "success", "text": f"Busca #{selected_id} pausada."}
        st.rerun()
    if b[1].button("▶️ Reativar", key="ctrl_resume", use_container_width=True, disabled=sel.status == "active"):
        resume_search(selected_id)
        st.session_state["ctrl_feedback"] = {"level": "success", "text": f"Busca #{selected_id} reativada."}
        st.rerun()
    if b[2].button("🚀 Executar agora", key="ctrl_run", type="primary", use_container_width=True):
        with st.spinner("Executando esta busca…"):
            res = run_now(selected_id)
        st.session_state["ctrl_feedback"] = {
            "level": "success" if res.get("ok") else "warning", "text": res.get("message", "Concluído."),
        }
        bump_data_version()  # new quotes were saved — refresh the dashboard
        st.rerun()
    if b[3].button("📑 Duplicar", key="ctrl_dup", use_container_width=True):
        new_id = duplicate_search(selected_id)
        st.session_state["ctrl_feedback"] = {"level": "success", "text": f"Busca duplicada como #{new_id}. Ajuste as datas se necessário."}
        st.rerun()

    # Destructive: delete with confirmation
    with st.expander("🗑️ Deletar busca", expanded=False):
        confirm = st.checkbox("Confirmo que desejo deletar esta busca programada.", key="ctrl_del_confirm")
        st.caption("Soft delete: o histórico de cotações e alertas é preservado; o worker para de executá-la.")
        if st.button("Deletar definitivamente do painel", key="ctrl_delete", disabled=not confirm):
            delete_search(selected_id)
            st.session_state["ctrl_feedback"] = {"level": "success", "text": f"Busca #{selected_id} deletada (soft delete)."}
            st.rerun()

    # Frequency + Telegram editors
    e = st.columns(2)
    with e[0]:
        cur_label = next((k for k, v in _CTRL_FREQ_OPTIONS.items() if v == sel.frequency_minutes), "1 hora")
        new_freq = st.selectbox("Frequência de execução", list(_CTRL_FREQ_OPTIONS.keys()),
                                index=list(_CTRL_FREQ_OPTIONS.keys()).index(cur_label), key="ctrl_freq")
        if st.button("Salvar frequência", key="ctrl_freq_save", use_container_width=True):
            set_frequency(selected_id, _CTRL_FREQ_OPTIONS[new_freq])
            st.session_state["ctrl_feedback"] = {"level": "success", "text": f"Frequência atualizada para {new_freq}."}
            st.rerun()
    with e[1]:
        tg = st.toggle("Alertas Telegram para esta busca", value=sel.telegram_enabled, key="ctrl_tg")
        if tg != sel.telegram_enabled:
            set_telegram(selected_id, tg)
            st.session_state["ctrl_feedback"] = {"level": "success",
                "text": f"Telegram {'ativado' if tg else 'desativado'} para a busca #{selected_id}."}
            st.rerun()

    # Detail expanders
    with st.expander("📋 Ver detalhes (todos os parâmetros)"):
        st.json({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in sel.as_dict().items()})

    with st.expander("💰 Ver últimos resultados"):
        rows = latest_quotes_for_search(selected_id)
        if rows:
            dfres = pd.DataFrame(rows)
            dfres["price"] = dfres["price"].map(money)
            dfres["airline"] = dfres["airline"].map(get_airline_name)
            dfres["departure_date"] = dfres["departure_date"].map(format_date)
            dfres["collected_at"] = dfres["collected_at"].map(format_datetime)
            dfres.columns = ["Origem", "Destino", "Companhia", "Preço", "Ida", "Provider", "Classificação", "Coletado em"]
            st.dataframe(dfres, use_container_width=True, hide_index=True)
        else:
            st.caption("Sem cotações coletadas para esta busca ainda.")

    with st.expander("📨 Ver alertas enviados"):
        alerts = alerts_for_search(selected_id)
        if alerts:
            for a in alerts:
                st.markdown(f"**{a['channel']}** · {a['status']} · {format_datetime(a['created_at'])}")
        else:
            st.caption("Nenhum alerta enviado para esta busca.")

    with st.expander("🕒 Histórico de execuções"):
        runs = get_run_logs(selected_id)
        if runs:
            dfr = pd.DataFrame(runs)
            dfr["started_at"] = dfr["started_at"].map(format_datetime)
            dfr["best_price"] = dfr["best_price"].map(lambda p: money(p) if p else "—")
            dfr = dfr[["started_at", "status", "quotes_found", "best_price", "source", "error_message"]]
            dfr.columns = ["Início", "Status", "Cotações", "Menor preço", "Origem", "Erro"]
            st.dataframe(dfr, use_container_width=True, hide_index=True)
        else:
            st.caption("Esta busca ainda não foi executada.")

    with st.expander("🧾 Auditoria de ações"):
        logs = get_action_logs(selected_id)
        if logs:
            for a in logs:
                st.markdown(f"`{format_datetime(a['created_at'])}` — **{a['action']}** "
                            f"({a['previous_status']} → {a['new_status']}) {a['message'] or ''}")
        else:
            st.caption("Nenhuma ação registrada.")


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

    # ── Manutenção / retenção do banco ────────────────────────────────────────
    st.divider()
    st.markdown("**🧹 Manutenção do banco**")
    st.caption(
        "Remove apenas cotações **antigas e já superadas** (snapshots que deixaram de ser o "
        "preço vigente). Preços atuais, buscas, alertas e o histórico recente são preservados. "
        "O monitor já faz essa limpeza automaticamente a cada execução."
    )
    keep_days = st.slider("Manter histórico dos últimos (dias)", min_value=30, max_value=365, value=90, step=30)
    if st.button(f"Limpar cotações superadas com mais de {keep_days} dias", use_container_width=True):
        from services.database_service import prune_old_quotes
        try:
            with session_scope() as db:
                result = prune_old_quotes(db, keep_days=keep_days)
            st.success(
                f"🧹 Limpeza concluída: {result['quotes_deleted']} cotação(ões) antiga(s) e "
                f"{result['logs_deleted']} log(s) removido(s). Histórico dos últimos {keep_days} dias preservado."
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Não foi possível limpar agora: {exc}")


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

    df_quotes = load_quotes_df(_data_version())
    real_df_quotes = filter_real_quotes_df(df_quotes)

    # Navegação simplificada (Histórico técnico, Oportunidades e Milhas saíram).
    tab_home, tab_control, tab_settings = st.tabs(
        ["🏠 Início", "🛰️ Controle de Buscas", "⚙️ Configurações"]
    )

    with tab_home:
        render_home_tab(summary, real_df_quotes, provider_status)

    with tab_control:
        render_search_control(summary, real_df_quotes)

    with tab_settings:
        render_settings(provider_status, db_connected)


if __name__ == "__main__":
    main()
