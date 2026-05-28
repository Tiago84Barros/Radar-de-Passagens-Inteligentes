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
except ImportError:  # pragma: no cover - keeps older deployments alive during cache refresh.
    def resolver_search_locations(value: str) -> list[LocationResolution]:
        location = resolve_location(value)
        return [location] if location else []
from app.monitor import run_due_searches, run_search_once
from app.settings import get_settings
from app.styles import load_custom_css
from providers.travelpayouts_provider import TravelPayoutsProvider, TravelPayoutsProviderError


st.set_page_config(
    page_title="Radar de Passagens Inteligentes",
    page_icon=":airplane:",
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


def require_password() -> None:
    settings = get_settings()
    if not settings.app_password:
        return
    if st.session_state.get("authenticated"):
        return
    load_custom_css()
    st.markdown(
        '<div class="top-shell"><div><p class="radar-title">Radar de Passagens Inteligentes</p>'
        '<div class="radar-subtitle">Acesso protegido para o dashboard.</div></div></div>',
        unsafe_allow_html=True,
    )
    password = st.text_input("Senha do app", type="password")
    if st.button("Entrar", type="primary"):
        if password == settings.app_password:
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Senha inválida.")
    st.stop()


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

    metrics = [
        ("Menor preço anual", money(best_overall["preço"].min()), f"{origin} -> {destination}"),
        ("Preço médio anual", money(best_overall["preço"].mean()), "Menores tarifas por data"),
        ("Companhias", best_by_airline["companhia"].nunique(), "Com cotações registradas"),
        ("Datas mapeadas", best_overall["ida_dt"].nunique(), "Dentro dos próximos 12 meses"),
    ]
    render_metric_cards(metrics)

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
    fig.update_layout(height=430, margin=dict(l=8, r=8, t=20, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

    table = best_overall.sort_values("preço").head(12)[["ida_dt", "companhia", "preço", "provedor", "link"]].copy()
    table["data de ida"] = table["ida_dt"].map(format_date)
    table["preço"] = table["preço"].map(format_brl)
    table = table[["data de ida", "companhia", "preço", "provedor", "link"]]
    st.dataframe(table, use_container_width=True, hide_index=True)


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
        rows.append(
            {
                "id": quote.id,
                "search_id": quote.search_id,
                "rota": f"{quote.origin} → {quote.destination}",
                "origem": quote.origin,
                "destino": quote.destination,
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


def duration_label(minutes: int | None) -> str:
    if not minutes:
        return "-"
    hours, mins = divmod(int(minutes), 60)
    return f"{hours}h {mins:02d}min"


def frequency_label(minutes: int | None) -> str:
    labels = {30: "30 min", 60: "1h", 180: "3h", 360: "6h", 720: "12h"}
    return labels.get(int(minutes or 0), f"{minutes} min")


def opportunity_score(opportunity: str, economy: float | None, max_price: float | None) -> int:
    base = {
        "normal": 45,
        "boa_oportunidade": 68,
        "excelente_oportunidade": 84,
        "oportunidade_rara": 95,
    }.get(opportunity, 50)
    if economy is not None and max_price:
        base += min(max((economy / max_price) * 20, 0), 10)
    return int(min(round(base), 100))


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


def status_badge(label: str, status: str = "neutral") -> str:
    return f'<span class="status-pill status-{status}">{label}</span>'


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


def render_header(provider_status: dict[str, Any], latest_provider_log: ProviderLog | None = None) -> None:
    load_custom_css()
    if provider_status["demo_mode"]:
        st.markdown(
            '<div class="demo-banner">Modo demonstração: configure a Travelpayouts para buscar passagens reais.</div>',
            unsafe_allow_html=True,
        )
    elif latest_provider_log and latest_provider_log.status == "real_failed_fallback":
        st.markdown(
            f'<div class="demo-banner">Travelpayouts configurada, mas a ultima consulta falhou e usou fallback demo. '
            f'Motivo: {latest_provider_log.error_message or "erro nao informado"}</div>',
            unsafe_allow_html=True,
        )
    elif latest_provider_log and latest_provider_log.status == "real_empty":
        st.markdown(
            '<div class="demo-banner">Travelpayouts respondeu, mas nao encontrou cotacoes para a ultima rota/data pesquisada.</div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        f"""
        <div class="top-shell">
            <div>
                <div class="top-kicker">Monitoramento de tarifas aéreas</div>
                <p class="radar-title">Radar de Passagens Inteligentes</p>
                <div class="radar-subtitle">
                    Monitore rotas, detecte quedas de preço e receba alertas automáticos.
                </div>
            </div>
            <div class="hero-status">
                <div class="hero-status-title">Status operacional</div>
                {status_badge("Modo demo", "warn") if provider_status["demo_mode"] else status_badge("API real", "ok")}
                <div class="opportunity-detail">Provider: {provider_status["provider_label"]}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_cards(values: list[tuple], per_row: int = 4) -> None:
    for start in range(0, len(values), per_row):
        cols = st.columns(min(per_row, len(values) - start))
        for col, metric in zip(cols, values[start:start + per_row]):
            label, value, help_text = metric[:3]
            indicator = metric[3] if len(metric) > 3 else "Atualizado"
            col.markdown(
                f"""
                <div class="metric-card">
                    <div class="metric-label">{label}</div>
                    <div class="metric-value">{value}</div>
                    <div class="metric-help">{help_text}</div>
                    <div class="metric-indicator">{indicator}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_top_metrics(summary: dict, df: pd.DataFrame) -> None:
    metrics = build_metrics(summary, df)
    render_metric_cards(
        [
            ("Buscas ativas", metrics["active"], "Rotinas em monitoramento", "Online"),
            ("Menor preço 24h", money(metrics["lowest_24h"]), "Cotação mínima recente", "24h"),
            ("Oportunidades", metrics["opportunities"], "Boas, ótimas e excelentes", "Score ativo"),
            ("Alertas enviados", metrics["alerts"], "Telegram/e-mail", "Historico real"),
            ("Economia potencial", money(metrics["economy"]), "Soma vs. preço máximo", "Estimado"),
            ("Última execução", format_datetime(metrics["latest_search"]), "Robô de busca", "Monitor"),
        ],
        per_row=3,
    )


def render_sidebar(summary: dict, provider_status: dict[str, Any], db_connected: bool) -> None:
    settings = get_settings()
    with st.sidebar:
        st.title("Radar de Passagens")
        st.caption("Painel de controle")
        st.subheader("Nova busca de passagem")
        if st.session_state.get("last_location_resolution"):
            st.info(st.session_state["last_location_resolution"])
        origin_input, selected_origin = _render_location_picker("Origem", "origin")
        destination_input, selected_destination = _render_location_picker("Destino", "destination")
        with st.form("new_search_form", clear_on_submit=False):
            departure = st.date_input("Data de ida", value=None)
            trip_label = st.selectbox("Tipo de viagem", list(TRIP_TYPE_OPTIONS.keys()), index=1)
            return_date = st.date_input(
                "Data de volta opcional",
                value=None,
                disabled=TRIP_TYPE_OPTIONS[trip_label] == "one_way",
            )
            adults = st.number_input("Adultos", min_value=1, max_value=9, value=1)
            max_price = st.number_input("Preço máximo desejado", min_value=100.0, value=3200.0, step=50.0)
            currency = st.selectbox("Moeda", ["BRL", "USD", "EUR"], index=0)
            flexibility = st.selectbox("Flexibilidade de datas", list(FLEXIBILITY_OPTIONS.keys()))
            frequency_label_selected = st.selectbox("Frequência de busca automática", list(FREQUENCY_OPTIONS.keys()), index=1)
            telegram_enabled = st.toggle("Ativar alerta Telegram", value=bool(settings.telegram_bot_token and settings.telegram_chat_id))
            search_now = st.form_submit_button("Buscar agora", use_container_width=True)
            start_monitoring = st.form_submit_button("Iniciar monitoramento", type="primary", use_container_width=True)

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
                    f"Busca resolvida como {origin_location.label} -> {destination_location.label}."
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
                    st.success(f"Monitoramento iniciado. {saved} cotação(ões) salvas.")
                else:
                    st.success(f"Busca concluída. {saved} cotação(ões) salvas.")
                st.rerun()

        st.divider()
        st.subheader("Status do sistema")
        telegram_ok = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        status_rows = [
            ("Banco conectado", "Sim" if db_connected else "Não"),
            ("Provider ativo", provider_status["provider_label"]),
            ("Travelpayouts", "Ativo" if settings.travelpayouts_api_token else "Inativo"),
            ("Scraping Azul/GOL/LATAM", "Ativo" if settings.enable_airline_scrapers else "Inativo"),
            ("Modo", "Demonstração" if provider_status["demo_mode"] else "Travelpayouts real"),
            ("Telegram configurado", "Sim" if telegram_ok else "Não"),
            ("Última busca executada", format_datetime(summary.get("latest_search"))),
            ("Buscas ativas", summary["active"]),
        ]
        latest_provider_log = summary.get("latest_provider_log")
        if latest_provider_log:
            status_rows.insert(3, ("Ultimo status API", latest_provider_log.status))
        for label, value in status_rows:
            st.markdown(
                f'<div class="status-row"><span class="status-label">{label}</span>'
                f'<span class="status-value">{value}</span></div>',
                unsafe_allow_html=True,
            )

        st.divider()
        if st.button("Rodar buscas devidas agora", use_container_width=True):
            result = run_due_searches(force=False)
            st.success(f"{result['searches_checked']} buscas checadas; {result['quotes_saved']} cotações salvas.")
            st.rerun()


def render_overview(summary: dict, df: pd.DataFrame) -> None:
    st.subheader("Resumo do radar")
    st.markdown(
        f"""
        <div class="soft-card">
            <div class="section-note">
                O radar acompanha {summary["routes"]} rota(s), mantém {summary["active"]} busca(s) ativa(s)
                e registrou {len(df)} cotação(ões) recentes para análise.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    st.subheader("Últimas cotações")
    if df.empty:
        st.info("As últimas cotações aparecerão aqui assim que o primeiro monitoramento rodar.")
        return
    latest_source = df.copy()
    latest_source["detectado_em_dt"] = safe_datetime_series(latest_source["detectado_em"])
    latest = latest_source.sort_values("detectado_em_dt", ascending=False).head(8)[
        ["rota", "ida", "volta", "companhia", "preço", "moeda", "classificação", "provedor", "detectado_em"]
    ].copy()
    latest["ida"] = latest["ida"].map(format_date)
    latest["volta"] = latest["volta"].map(format_date)
    latest["preço"] = latest["preço"].map(format_brl)
    latest["detectado_em"] = latest["detectado_em"].map(format_datetime)
    st.dataframe(latest, use_container_width=True, hide_index=True)


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
            col.markdown(
                f"""
                <div class="{card_class}">
                    <span class="tag {tag_class}">{row['classificação']}</span>
                    <span class="tag {alert_class}">{alert_label}</span>
                    <div class="opportunity-route">{row['rota']}</div>
                    <div class="opportunity-detail">Ida: {format_date(row['ida'])} · Volta: {format_date(row['volta'])}</div>
                    <div class="opportunity-price">{format_brl(row['preço'])}</div>
                    <div class="opportunity-detail">Preço máximo: {money(row['preço máximo'], row['moeda'])}</div>
                    <div class="opportunity-detail">Economia estimada: {money(economy, row['moeda'])}</div>
                    <div class="opportunity-detail">Score: {row['score']}/100</div>
                    <div class="opportunity-detail">Companhia: {row['companhia']}</div>
                    <div class="opportunity-detail">Provider: {row['provedor']}</div>
                    <div class="opportunity-detail">Duração: {row['duração']} · Escalas: {row['escalas']}</div>
                    <div class="opportunity-detail"><a class="buy-link" href="{row['link']}" target="_blank">Abrir link de compra</a></div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_searches(summary: dict, df_quotes: pd.DataFrame) -> None:
    st.subheader("Buscas ativas")
    searches = summary["searches"]
    if not searches:
        st.info("Nenhuma busca cadastrada. O painel de criação fica na sidebar.")
        return
    df = searches_df(searches, df_quotes)
    display = df.copy()
    display["data de ida"] = display["data de ida"].map(format_date)
    display["data de volta"] = display["data de volta"].map(format_date)
    display["última consulta"] = display["última consulta"].map(format_datetime)
    display["preço máximo"] = display["preço máximo"].map(money)
    display["menor preço encontrado"] = display["menor preço encontrado"].map(money)
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.markdown("**Pausar ou reativar monitoramento**")
    for start in range(0, len(searches), 4):
        cols = st.columns(4)
        for col, search in zip(cols, searches[start:start + 4]):
            action = "Pausar" if search.is_active else "Reativar"
            label = f"{action} #{search.id} · {search.origin}-{search.destination}"
            if col.button(label, key=f"toggle-search-{search.id}", use_container_width=True):
                with session_scope() as db:
                    item = db.get(FlightSearch, search.id)
                    if item:
                        item.is_active = not item.is_active
                st.rerun()


def render_history(df: pd.DataFrame) -> None:
    st.subheader("Histórico de preços")
    if df.empty:
        st.info("Ainda não há histórico de cotações.")
        return
    routes = ["Todas"] + sorted(df["rota"].unique().tolist())
    route = st.selectbox("Filtrar por rota", routes)
    filtered = df if route == "Todas" else df[df["rota"] == route]
    metrics = [
        ("Menor histórico", money(filtered["preço"].min()), "Mínimo registrado"),
        ("Preço médio", money(filtered["preço"].mean()), "Média das cotações"),
        ("Maior preço", money(filtered["preço"].max()), "Máximo registrado"),
        (
            "Variação",
            f"{(((filtered['preço'].max() - filtered['preço'].min()) / filtered['preço'].min()) * 100):.1f}%" if filtered["preço"].min() else "-",
            "Entre mínimo e máximo",
        ),
    ]
    render_metric_cards(metrics)
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
    table["ida"] = table["ida"].map(format_date)
    table["volta"] = table["volta"].map(format_date)
    table["preço"] = table["preço"].map(format_brl)
    table["detectado_em"] = table["detectado_em"].map(format_datetime)
    st.dataframe(table, use_container_width=True, hide_index=True)


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
        {"configuração": "Azul Scraper", "status": "Ativo" if settings.enable_airline_scrapers else "Inativo"},
        {"configuração": "GOL Scraper", "status": "Ativo" if settings.enable_airline_scrapers else "Inativo"},
        {"configuração": "LATAM Scraper", "status": "Ativo" if settings.enable_airline_scrapers else "Inativo"},
        {"configuração": "TELEGRAM_BOT_TOKEN", "status": "Configurado" if settings.telegram_bot_token else "Não configurado"},
        {"configuração": "TELEGRAM_CHAT_ID", "status": "Configurado" if settings.telegram_chat_id else "Não configurado"},
        {"configuração": "Provider ativo", "status": provider_status["provider_label"]},
        {"configuração": "Modo atual", "status": "Demonstração" if provider_status["demo_mode"] else "Travelpayouts real"},
        {"configuração": "Banco", "status": "Conectado" if db_connected else "Indisponível"},
    ]
    st.dataframe(pd.DataFrame(provider_rows), use_container_width=True, hide_index=True)
    st.markdown("**Teste de conexao Travelpayouts**")
    if st.button("Testar conexao com Travelpayouts", use_container_width=True):
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
                    st.success("Conexao com Travelpayouts realizada com sucesso. A API retornou cotacoes reais.")
                else:
                    st.info("Conexao com Travelpayouts realizada, mas a API nao retornou cotacoes para a rota de teste.")
            except TravelPayoutsProviderError as exc:
                st.error(str(exc))
    latest_provider_log = load_summary().get("latest_provider_log")
    if latest_provider_log:
        st.markdown("**Ultimo diagnostico Travelpayouts**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "status": latest_provider_log.status,
                        "mensagem": latest_provider_log.error_message or "-",
                        "registrado_em": format_datetime(latest_provider_log.created_at),
                    }
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    st.markdown("**Como configurar secrets**")
    st.markdown(
        "Configure os secrets no Streamlit Cloud e também em `Settings > Secrets and variables > Actions` "
        "no GitHub para o robô agendado. O app nunca mostra os valores, apenas se eles existem."
    )
    st.markdown("**Para ativar a API Travelpayouts:**")
    st.markdown(
        """
1. Crie ou acesse sua conta Travelpayouts.
2. Copie seu API token.
3. No Streamlit Cloud, vá em App > Settings > Secrets.
4. Adicione:
        """
    )
    st.code(
        """TRAVELPAYOUTS_API_TOKEN = "seu_token"
TELEGRAM_BOT_TOKEN = "seu_bot_token"
TELEGRAM_CHAT_ID = "seu_chat_id" """,
        language="toml",
    )
    st.markdown(
        """
5. Salve e reinicie o app.
6. O modo atual deve mudar de demonstração para Travelpayouts real.
        """
    )
    st.markdown("**Secrets esperados**")
    st.code(
        """DATABASE_URL
APP_PASSWORD
TRAVELPAYOUTS_API_TOKEN
ENABLE_AIRLINE_SCRAPERS
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
ALERT_FROM_EMAIL""",
        language="text",
    )
    st.markdown("**Diagnóstico do banco**")
    st.json(database_diagnostics())


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
        st.write("Diagnóstico da conexão lida pelo app:")
        st.json(database_diagnostics())
        st.code(str(exc), language="text")
        st.stop()

    summary = load_summary()
    render_sidebar(summary, provider_status, db_connected)
    render_header(provider_status, summary.get("latest_provider_log"))
    df_quotes = quotes_df(summary["quotes"], summary["searches"], summary["latest_alert_by_quote"])
    real_df_quotes = filter_real_quotes_df(df_quotes)
    render_year_price_calendar(summary, real_df_quotes)
    st.write("")

    tab_overview, tab_opportunities, tab_searches, tab_history, tab_settings = st.tabs(
        ["Visão Geral", "Oportunidades", "Buscas Ativas", "Histórico de Preços", "Configurações"]
    )
    with tab_overview:
        render_overview(summary, real_df_quotes)
    with tab_opportunities:
        render_opportunities(real_df_quotes)
    with tab_searches:
        render_searches(summary, real_df_quotes)
    with tab_history:
        render_history(real_df_quotes)
    with tab_settings:
        render_settings(provider_status, db_connected)


if __name__ == "__main__":
    main()
