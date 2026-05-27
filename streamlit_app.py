from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import distinct, func, select

from app.db import AlertLog, FlightQuote, FlightSearch, init_db, session_scope
from app.monitor import run_due_searches, run_search_once
from app.settings import get_settings


st.set_page_config(
    page_title="Radar de Passagens Inteligentes",
    page_icon="✈️",
    layout="wide",
)


CSS = """
<style>
.main .block-container { padding-top: 1.4rem; }
.radar-hero {
    border: 1px solid rgba(19,200,163,.25);
    background: linear-gradient(135deg, rgba(19,200,163,.13), rgba(74,158,255,.08));
    border-radius: 14px;
    padding: 22px 24px;
    margin-bottom: 18px;
}
.radar-title { color: #F8FAFC; font-size: 1.8rem; font-weight: 900; margin: 0; }
.radar-subtitle { color: #AEB8C8; margin-top: 7px; line-height: 1.5; }
.metric-card {
    border: 1px solid #253248;
    background: #101827;
    border-radius: 12px;
    padding: 16px 18px;
}
.metric-label { color: #8EA0B8; font-size: .72rem; text-transform: uppercase; letter-spacing: .12em; font-weight: 850; }
.metric-value { color: #F8FAFC; font-size: 1.7rem; font-weight: 950; margin-top: 6px; }
.metric-help { color: #718096; font-size: .82rem; margin-top: 4px; }
.opportunity-card {
    border: 1px solid #253248;
    background: #0F172A;
    border-radius: 12px;
    padding: 15px 16px;
    min-height: 170px;
}
.opportunity-route { color: #F8FAFC; font-weight: 900; font-size: 1.05rem; }
.opportunity-price { color: #13C8A3; font-weight: 950; font-size: 1.32rem; margin-top: 10px; }
.tag { display:inline-block; padding: 3px 8px; border-radius: 999px; background: rgba(19,200,163,.12); color: #7EF5D8; font-size: .7rem; font-weight: 800; }
</style>
"""


def require_password() -> None:
    settings = get_settings()
    if not settings.app_password:
        return
    if st.session_state.get("authenticated"):
        return
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="radar-hero"><p class="radar-title">Radar de Passagens Inteligentes</p><div class="radar-subtitle">Acesso protegido para o dashboard.</div></div>', unsafe_allow_html=True)
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


def money(value) -> str:
    if value is None:
        return "-"
    return f"R$ {float(value):,.0f}".replace(",", ".")


def load_summary() -> dict:
    with session_scope() as db:
        active = db.scalar(select(func.count()).select_from(FlightSearch).where(FlightSearch.is_active.is_(True))) or 0
        alerts = db.scalar(select(func.count()).select_from(AlertLog)) or 0
        lowest = None
        routes = db.scalar(select(func.count(distinct(FlightSearch.origin + FlightSearch.destination)))) or 0
        quotes = list(db.scalars(select(FlightQuote).order_by(FlightQuote.detected_at.desc()).limit(200)))
        searches = list(db.scalars(select(FlightSearch).order_by(FlightSearch.created_at.desc())))
    return {"active": active, "alerts": alerts, "lowest": lowest, "routes": routes, "quotes": quotes, "searches": searches}


def quotes_df(quotes: list[FlightQuote]) -> pd.DataFrame:
    rows = [
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
            "moeda": quote.currency,
            "duração_min": quote.duration_minutes,
            "escalas": quote.stops,
            "provedor": quote.provider,
            "oportunidade": quote.opportunity,
            "detectado_em": quote.detected_at,
            "link": quote.booking_link,
        }
        for quote in quotes
    ]
    return pd.DataFrame(rows)


def searches_df(searches: list[FlightSearch]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": search.id,
                "origem": search.origin,
                "destino": search.destination,
                "ida": search.departure_date,
                "volta": search.return_date,
                "passageiros": search.passengers,
                "preço alvo": search.max_price,
                "moeda": search.currency,
                "frequência min": search.frequency_minutes,
                "ativa": search.is_active,
                "última checagem": search.last_checked_at,
            }
            for search in searches
        ]
    )


def render_header() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="radar-hero">
            <p class="radar-title">Radar de Passagens Inteligentes</p>
            <div class="radar-subtitle">
                Dashboard para cadastrar rotas, monitorar cotações por providers, identificar quedas de preço
                e disparar alertas automáticos por Telegram/e-mail.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metrics(summary: dict, df: pd.DataFrame) -> None:
    lowest_24h = None
    if not df.empty:
        recent = df[pd.to_datetime(df["detectado_em"], utc=True) >= (pd.Timestamp.utcnow() - pd.Timedelta(hours=24))]
        if not recent.empty:
            lowest_24h = recent["preço"].min()
    cols = st.columns(4)
    values = [
        ("Buscas ativas", summary["active"], "Rotinas em monitoramento"),
        ("Alertas disparados", summary["alerts"], "Telegram/e-mail ou mock"),
        ("Menor preço 24h", money(lowest_24h), "Cotação mínima recente"),
        ("Rotas monitoradas", summary["routes"], "Origem e destino únicos"),
    ]
    for col, (label, value, help_text) in zip(cols, values):
        col.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{value}</div>
                <div class="metric-help">{help_text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_dashboard(summary: dict) -> None:
    df = quotes_df(summary["quotes"])
    render_metrics(summary, df)
    st.divider()
    left, right = st.columns([1.35, 1])
    with left:
        st.subheader("Evolução de preço por rota")
        if df.empty:
            st.info("Ainda não há cotações. Rode uma busca para gerar o histórico.")
        else:
            daily = df.copy()
            daily["dia"] = pd.to_datetime(daily["detectado_em"]).dt.date
            daily = daily.groupby(["dia", "rota"], as_index=False)["preço"].min()
            fig = px.line(daily, x="dia", y="preço", color="rota", markers=True)
            fig.update_layout(height=390, margin=dict(l=8, r=8, t=20, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Comparação entre provedores")
        if df.empty:
            st.info("Sem dados de providers ainda.")
        else:
            providers = df.groupby("provedor", as_index=False).agg(preço_min=("preço", "min"), preço_médio=("preço", "mean"))
            fig = px.bar(providers, x="provedor", y=["preço_min", "preço_médio"], barmode="group")
            fig.update_layout(height=390, margin=dict(l=8, r=8, t=20, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Oportunidades recentes")
    if df.empty:
        st.caption("Nenhuma oportunidade registrada.")
        return
    for row_cols in range(0, min(len(df), 8), 4):
        cols = st.columns(4)
        for col, (_, row) in zip(cols, df.head(8).iloc[row_cols:row_cols + 4].iterrows()):
            col.markdown(
                f"""
                <div class="opportunity-card">
                    <span class="tag">{row['oportunidade']}</span>
                    <div class="opportunity-route">{row['rota']}</div>
                    <div class="opportunity-price">{row['moeda']} {row['preço']:,.0f}</div>
                    <div style="color:#AEB8C8;font-size:.82rem;margin-top:8px;">{row['companhia']} · {row['provedor']} · {row['escalas']} escala(s)</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_new_search() -> None:
    st.subheader("Cadastrar monitoramento")
    with st.form("new_search_form"):
        c1, c2, c3, c4 = st.columns(4)
        origin = c1.text_input("Origem", "GRU").upper()
        destination = c2.text_input("Destino ou ANYWHERE", "LIS").upper()
        departure = c3.date_input("Data de ida", date.today() + timedelta(days=60))
        return_date = c4.date_input("Data de volta opcional", date.today() + timedelta(days=75))
        c5, c6, c7, c8 = st.columns(4)
        passengers = c5.number_input("Passageiros", min_value=1, max_value=9, value=1)
        max_price = c6.number_input("Preço máximo desejado", min_value=100.0, value=3200.0, step=50.0)
        currency = c7.selectbox("Moeda", ["BRL", "USD", "EUR"])
        frequency = c8.selectbox("Frequência de busca", [30, 60, 180, 360, 720], index=1)
        c9, c10, c11, c12 = st.columns(4)
        trip_type = c9.selectbox("Tipo de viagem", ["round_trip", "one_way", "multi_city"])
        flexible = c10.checkbox("Datas flexíveis", value=True)
        baggage = c11.checkbox("Bagagem incluída", value=False)
        owner_email = c12.text_input("E-mail para alerta", "demo@radar.local")
        allowed = st.text_input("Companhias permitidas", placeholder="LATAM,TAP")
        blocked = st.text_input("Companhias bloqueadas", placeholder="Companhias a evitar")
        submitted = st.form_submit_button("Salvar busca", type="primary")
    if submitted:
        with session_scope() as db:
            search = FlightSearch(
                owner_email=owner_email,
                origin=origin,
                destination=destination or "ANYWHERE",
                departure_date=departure,
                return_date=return_date if trip_type != "one_way" else None,
                flexible_dates=flexible,
                passengers=int(passengers),
                max_price=float(max_price),
                currency=currency,
                trip_type=trip_type,
                allowed_airlines=allowed or None,
                blocked_airlines=blocked or None,
                baggage_included=baggage,
                frequency_minutes=int(frequency),
            )
            db.add(search)
        st.success("Busca cadastrada. Ela já pode ser executada manualmente ou pelo GitHub Actions.")
        st.rerun()


def render_searches(summary: dict) -> None:
    st.subheader("Buscas monitoradas")
    searches = summary["searches"]
    if not searches:
        st.info("Nenhuma busca cadastrada.")
        return
    st.dataframe(searches_df(searches), use_container_width=True, hide_index=True)
    c1, c2 = st.columns([1, 3])
    search_id = c1.selectbox("Busca para rodar agora", [search.id for search in searches])
    if c2.button("Rodar busca selecionada agora", type="primary"):
        with session_scope() as db:
            search = db.get(FlightSearch, int(search_id))
            if search:
                saved = run_search_once(db, search)
                st.success(f"Busca executada. {saved} cotações salvas.")
        st.rerun()
    if st.button("Rodar todas as buscas devidas agora"):
        result = run_due_searches(force=False)
        st.success(f"{result['searches_checked']} buscas checadas; {result['quotes_saved']} cotações salvas.")
        st.rerun()


def render_history(summary: dict) -> None:
    st.subheader("Histórico e análise")
    df = quotes_df(summary["quotes"])
    if df.empty:
        st.info("Ainda não há histórico.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)
    c1, c2, c3 = st.columns(3)
    df["weekday"] = pd.to_datetime(df["detectado_em"]).dt.day_name()
    df["hour"] = pd.to_datetime(df["detectado_em"]).dt.hour
    c1.markdown("**Melhores dias da semana**")
    c1.dataframe(df.groupby("weekday", as_index=False)["preço"].min().sort_values("preço"), hide_index=True)
    c2.markdown("**Melhores horários de detecção**")
    c2.dataframe(df.groupby("hour", as_index=False)["preço"].min().sort_values("preço"), hide_index=True)
    c3.markdown("**Rotas com menor preço**")
    c3.dataframe(df.groupby("rota", as_index=False)["preço"].min().sort_values("preço"), hide_index=True)


def render_setup() -> None:
    st.subheader("Configuração para deploy")
    st.markdown(
        """
        **Streamlit Cloud:** use `streamlit_app.py` como entrypoint.

        **GitHub Actions:** configure os mesmos secrets usados pelo app para o robô agendado:
        `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, chaves de providers e SMTP.

        **Supabase:** crie um projeto Postgres e use a string de conexão em `DATABASE_URL`.
        """
    )


def main() -> None:
    init_db()
    seed_if_empty()
    require_password()
    render_header()
    summary = load_summary()
    tab_dashboard, tab_new, tab_searches, tab_history, tab_setup = st.tabs(
        ["Dashboard", "Novo monitoramento", "Buscas ativas", "Histórico", "Configuração"]
    )
    with tab_dashboard:
        render_dashboard(summary)
    with tab_new:
        render_new_search()
    with tab_searches:
        render_searches(summary)
    with tab_history:
        render_history(summary)
    with tab_setup:
        render_setup()


if __name__ == "__main__":
    main()
