from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select

from app.db import AlertLog, FlightQuote, FlightSearch, database_diagnostics, init_db, session_scope
from app.monitor import run_due_searches, run_search_once
from app.settings import get_settings
from app.styles import load_custom_css


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
}


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


def seed_if_empty() -> None:
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
    if value is None or pd.isna(value):
        return "-"
    return f"{currency} {float(value):,.0f}".replace(",", ".")


def format_datetime(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    if isinstance(value, str):
        return value
    return pd.to_datetime(value).strftime("%d/%m/%Y %H:%M")


def format_date(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.to_datetime(value).strftime("%d/%m/%Y")


def get_provider_status(settings) -> dict[str, Any]:
    providers = {
        "Amadeus": bool(settings.amadeus_client_id and settings.amadeus_client_secret),
        "Kiwi/Tequila": bool(settings.kiwi_api_key),
        "TravelPayouts": bool(settings.travelpayouts_token),
    }
    active = [name for name, configured in providers.items() if configured]
    return {
        "providers": providers,
        "active_names": active,
        "provider_label": ", ".join(active) if active else "Mocks internos",
        "demo_mode": not bool(active),
    }


def load_summary() -> dict:
    with session_scope() as db:
        active = db.scalar(select(func.count()).select_from(FlightSearch).where(FlightSearch.is_active.is_(True))) or 0
        alerts = db.scalar(select(func.count()).select_from(AlertLog)) or 0
        quotes = list(db.scalars(select(FlightQuote).order_by(FlightQuote.detected_at.desc()).limit(500)))
        searches = list(db.scalars(select(FlightSearch).order_by(FlightSearch.created_at.desc())))
        latest_search = db.scalar(select(func.max(FlightSearch.last_checked_at)))
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
        score = opportunity_score(quote.opportunity, economy, max_price)
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
                "score": score,
                "moeda": quote.currency,
                "duração_min": quote.duration_minutes,
                "duração": duration_label(quote.duration_minutes),
                "escalas": quote.stops,
                "provedor": quote.provider,
                "oportunidade": quote.opportunity,
                "classificação": OPPORTUNITY_LABELS.get(quote.opportunity, quote.opportunity),
                "detectado_em": quote.detected_at,
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
        recent = df[pd.to_datetime(df["detectado_em"], utc=True) >= (pd.Timestamp.utcnow() - pd.Timedelta(hours=24))]
    positive_economy = df["economia"].clip(lower=0).sum() if not df.empty and "economia" in df else 0
    classified = {"boa_oportunidade", "excelente_oportunidade", "oportunidade_rara"}
    return {
        "active": summary["active"],
        "alerts": summary["alerts"],
        "lowest_24h": None if recent.empty else recent["preço"].min(),
        "economy": positive_economy,
        "opportunities": 0 if df.empty else int(df["oportunidade"].isin(classified).sum()),
        "latest_search": summary["latest_search"],
    }


def status_badge(label: str, status: str = "neutral") -> str:
    return f'<span class="status-pill status-{status}">{label}</span>'


def render_header(provider_status: dict[str, Any]) -> None:
    load_custom_css()
    if provider_status["demo_mode"]:
        st.markdown(
            '<div class="demo-banner">Modo demo ativo: nenhuma API real de passagens está configurada. '
            "As cotações exibidas são simuladas.</div>",
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
            ("Alertas enviados", metrics["alerts"], "Telegram/e-mail ou mock", "Histórico"),
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
        st.subheader("Nova busca")
        with st.form("new_search_form", clear_on_submit=False):
            origin = st.text_input("Partida/origem", "GRU").strip().upper()
            destination = st.text_input("Destino", "LIS").strip().upper()
            departure = st.date_input("Data de ida", date.today() + timedelta(days=60))
            trip_label = st.selectbox("Tipo de viagem", list(TRIP_TYPE_OPTIONS.keys()), index=1)
            return_date = st.date_input(
                "Data de volta opcional",
                date.today() + timedelta(days=75),
                disabled=TRIP_TYPE_OPTIONS[trip_label] == "one_way",
            )
            passengers = st.number_input("Quantidade de passageiros", min_value=1, max_value=9, value=1)
            max_price = st.number_input("Preço máximo desejado", min_value=100.0, value=3200.0, step=50.0)
            currency = st.selectbox("Moeda", ["BRL", "USD", "EUR"])
            flexibility = st.selectbox("Flexibilidade de datas", list(FLEXIBILITY_OPTIONS.keys()))
            frequency_label_selected = st.selectbox("Frequência de busca automática", list(FREQUENCY_OPTIONS.keys()), index=1)
            telegram_enabled = st.toggle("Ativar alerta Telegram", value=bool(settings.telegram_bot_token and settings.telegram_chat_id))
            submitted = st.form_submit_button("Iniciar monitoramento", type="primary", use_container_width=True)

        if submitted:
            if not origin or not destination:
                st.error("Informe origem e destino para iniciar o monitoramento.")
            elif telegram_enabled and not (settings.telegram_bot_token and settings.telegram_chat_id):
                st.warning("Telegram marcado, mas os secrets do Telegram ainda não estão configurados.")
            else:
                with session_scope() as db:
                    search = FlightSearch(
                        owner_email="demo@radar.local",
                        origin=origin,
                        destination=destination,
                        departure_date=departure,
                        return_date=return_date if TRIP_TYPE_OPTIONS[trip_label] == "round_trip" else None,
                        flexible_dates=FLEXIBILITY_OPTIONS[flexibility],
                        passengers=int(passengers),
                        max_price=float(max_price),
                        currency=currency,
                        trip_type=TRIP_TYPE_OPTIONS[trip_label],
                        baggage_included=False,
                        frequency_minutes=FREQUENCY_OPTIONS[frequency_label_selected],
                    )
                    db.add(search)
                st.success("Monitoramento iniciado.")
                st.rerun()

        st.divider()
        st.subheader("Status do sistema")
        telegram_ok = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        status_rows = [
            ("Banco conectado", "Sim" if db_connected else "Não"),
            ("Provider ativo", provider_status["provider_label"]),
            ("Modo", "Demo" if provider_status["demo_mode"] else "API real"),
            ("Telegram configurado", "Sim" if telegram_ok else "Não"),
            ("Última busca executada", format_datetime(summary.get("latest_search"))),
            ("Buscas ativas", summary["active"]),
        ]
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
    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("Evolução geral de preços")
        if df.empty:
            st.info("Ainda não há cotações. Crie uma busca na sidebar para gerar histórico.")
        else:
            daily = df.copy()
            daily["dia"] = pd.to_datetime(daily["detectado_em"]).dt.date
            daily = daily.groupby(["dia", "rota"], as_index=False)["preço"].min()
            fig = px.line(daily, x="dia", y="preço", color="rota", markers=True)
            fig.update_layout(height=390, margin=dict(l=8, r=8, t=20, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Status por provider")
        if df.empty:
            st.info("Sem dados de providers ainda.")
        else:
            providers = df.groupby("provedor", as_index=False).agg(preço_min=("preço", "min"), preço_médio=("preço", "mean"))
            fig = px.bar(providers, x="provedor", y=["preço_min", "preço_médio"], barmode="group")
            fig.update_layout(height=390, margin=dict(l=8, r=8, t=20, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
    st.subheader("Últimas cotações")
    if df.empty:
        st.info("As últimas cotações aparecerão aqui assim que o primeiro monitoramento rodar.")
        return
    latest = df.sort_values("detectado_em", ascending=False).head(8)[
        ["rota", "ida", "volta", "companhia", "preço", "moeda", "classificação", "provedor", "detectado_em"]
    ].copy()
    latest["ida"] = latest["ida"].map(format_date)
    latest["volta"] = latest["volta"].map(format_date)
    latest["detectado_em"] = latest["detectado_em"].map(format_datetime)
    st.dataframe(latest, use_container_width=True, hide_index=True)


def render_opportunities(df: pd.DataFrame) -> None:
    st.subheader("Oportunidades encontradas")
    if df.empty:
        st.info("Nenhuma passagem encontrada ainda. Use a sidebar para iniciar um monitoramento.")
        return
    opportunity_df = df[df["oportunidade"] != "normal"].copy()
    if opportunity_df.empty:
        st.info("Nenhuma oportunidade classificada como boa, ótima ou excelente até agora.")
        return
    ordered = opportunity_df.sort_values(["score", "economia", "detectado_em"], ascending=[False, False, False]).head(12)
    for start in range(0, len(ordered), 3):
        cols = st.columns(3)
        for col, (_, row) in zip(cols, ordered.iloc[start:start + 3].iterrows()):
            alert_label = "Alerta enviado" if row["alerta"] not in {"-", "failed"} and not str(row["alerta"]).startswith("failed") else "Sem alerta"
            alert_class = "tag-alert" if alert_label == "Alerta enviado" else "tag-muted"
            economy = row["economia"] if row["economia"] is not None else 0
            card_class = "opportunity-card excellent" if row["oportunidade"] in {"excelente_oportunidade", "oportunidade_rara"} else "opportunity-card"
            tag_class = {
                "boa_oportunidade": "tag-good",
                "excelente_oportunidade": "tag-excellent",
                "oportunidade_rara": "tag-great",
            }.get(row["oportunidade"], "tag-muted")
            col.markdown(
                f"""
                <div class="{card_class}">
                    <span class="tag {tag_class}">{row['classificação']}</span>
                    <span class="tag {alert_class}">{alert_label}</span>
                    <div class="opportunity-route">{row['rota']}</div>
                    <div class="opportunity-detail">Ida: {format_date(row['ida'])} · Volta: {format_date(row['volta'])}</div>
                    <div class="opportunity-price">{row['moeda']} {row['preço']:,.0f}</div>
                    <div class="opportunity-detail">Preço máximo: {money(row['preço máximo'], row['moeda'])}</div>
                    <div class="opportunity-detail">Economia estimada: {money(economy, row['moeda'])}</div>
                    <div class="opportunity-detail">Score: {row['score']}/100</div>
                    <div class="opportunity-detail">Companhia: {row['companhia']}</div>
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
    chart_df["detectado_em"] = pd.to_datetime(chart_df["detectado_em"])
    fig = px.line(chart_df.sort_values("detectado_em"), x="detectado_em", y="preço", color="rota", markers=True)
    fig.update_layout(height=420, margin=dict(l=8, r=8, t=20, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)
    table = filtered[
        ["rota", "ida", "volta", "companhia", "preço", "moeda", "provedor", "classificação", "detectado_em", "link"]
    ].copy()
    table["ida"] = table["ida"].map(format_date)
    table["volta"] = table["volta"].map(format_date)
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
        {"configuração": "AMADEUS_CLIENT_ID", "status": "Configurado" if settings.amadeus_client_id else "Não configurado"},
        {"configuração": "AMADEUS_CLIENT_SECRET", "status": "Configurado" if settings.amadeus_client_secret else "Não configurado"},
        {"configuração": "TELEGRAM_BOT_TOKEN", "status": "Configurado" if settings.telegram_bot_token else "Não configurado"},
        {"configuração": "TELEGRAM_CHAT_ID", "status": "Configurado" if settings.telegram_chat_id else "Não configurado"},
        {"configuração": "Provider ativo", "status": provider_status["provider_label"]},
        {"configuração": "Modo atual", "status": "Demo" if provider_status["demo_mode"] else "API real"},
        {"configuração": "Banco", "status": "Conectado" if db_connected else "Indisponível"},
    ]
    st.dataframe(pd.DataFrame(provider_rows), use_container_width=True, hide_index=True)
    st.markdown("**Como configurar secrets**")
    st.markdown(
        "Configure os secrets no Streamlit Cloud e também em `Settings > Secrets and variables > Actions` "
        "no GitHub para o robô agendado. O app nunca mostra os valores, apenas se eles existem."
    )
    st.code(
        """DATABASE_URL
APP_PASSWORD
AMADEUS_CLIENT_ID
AMADEUS_CLIENT_SECRET
KIWI_API_KEY
TRAVELPAYOUTS_TOKEN
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
        seed_if_empty()
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
    render_header(provider_status)
    df_quotes = quotes_df(summary["quotes"], summary["searches"], summary["latest_alert_by_quote"])
    render_top_metrics(summary, df_quotes)
    st.write("")

    tab_overview, tab_opportunities, tab_searches, tab_history, tab_settings = st.tabs(
        ["Visão Geral", "Oportunidades", "Buscas Ativas", "Histórico de Preços", "Configurações"]
    )
    with tab_overview:
        render_overview(summary, df_quotes)
    with tab_opportunities:
        render_opportunities(df_quotes)
    with tab_searches:
        render_searches(summary, df_quotes)
    with tab_history:
        render_history(df_quotes)
    with tab_settings:
        render_settings(provider_status, db_connected)


if __name__ == "__main__":
    main()
