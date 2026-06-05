"""Aba 'Radar Scraping' — mostra exclusivamente cotações capturadas por scraping.

Fontes de scraping reconhecidas: azul, gol, latam, google_flights.
Fonte de API: travelpayouts (e variantes).
Demo/mock: qualquer provider com 'demo', 'mock' ou 'fallback' no nome.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from app.db import FlightQuote, SearchRunLog, SourceLog, session_scope
from app.formatting import format_brl
from services.route_viability_service import (
    SCRAPER_SOURCES,
    calculate_route_viability,
)

# ── Constants ──────────────────────────────────────────────────────────────────

_DEMO_MARKERS = ("mock", "demo", "fallback", "demonstracao", "demonstra")

_AIRLINE_COLORS = {
    "Azul": "#1A4FA0",
    "GOL": "#F97316",
    "LATAM": "#E11D48",
    "Google Flights": "#34A853",
    "Copa Air": "#00205B",
}

_PROVIDER_LABELS = {
    "azul": "Azul",
    "gol": "GOL",
    "latam": "LATAM",
    "google_flights": "Google Flights",
    "copa_air": "Copa Air",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_demo(provider: str) -> bool:
    p = str(provider or "").lower()
    return any(m in p for m in _DEMO_MARKERS)


def _format_duration(minutes: int | float | None) -> str:
    if not minutes or pd.isna(minutes):
        return "—"
    m = int(minutes)
    h, rem = divmod(m, 60)
    return f"{h}h {rem:02d}min"


def _format_date(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        return "—" if pd.isna(ts) else ts.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)


def _format_date_short(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        return "—" if pd.isna(ts) else ts.strftime("%d/%m/%Y")
    except Exception:
        return str(value)


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_scraping_data() -> tuple[pd.DataFrame, list, list]:
    """Return (quotes_df, source_logs, run_logs) — all from the DB."""
    with session_scope() as db:
        quotes = list(
            db.scalars(
                select(FlightQuote)
                .where(FlightQuote.provider.in_(list(SCRAPER_SOURCES)))
                .order_by(FlightQuote.detected_at.desc())
                .limit(2000)
            )
        )
        source_logs = list(
            db.scalars(
                select(SourceLog)
                .where(SourceLog.source.in_(list(SCRAPER_SOURCES)))
                .order_by(SourceLog.created_at.desc())
                .limit(50)
            )
        )
        run_logs = list(
            db.scalars(
                select(SearchRunLog)
                .order_by(SearchRunLog.started_at.desc())
                .limit(30)
            )
        )

    rows = []
    for q in quotes:
        provider_clean = str(q.provider or "").lower()
        airline_label = _PROVIDER_LABELS.get(provider_clean, str(q.airline or q.provider or "—"))
        duration = int(q.duration_minutes or 0)
        price = float(q.price or 0)
        price_per_hour = round(price / (duration / 60), 2) if duration > 0 else None

        # Viability score
        v = calculate_route_viability({
            "price": price,
            "duration_minutes": duration,
            "stops": int(q.stops or 0),
            "provider": provider_clean,
            "booking_link": str(q.booking_link or ""),
        })

        rows.append({
            "id": q.id,
            "search_id": q.search_id,
            "origem": str(q.origin or ""),
            "destino": str(q.destination or ""),
            "companhia": airline_label,
            "provedor": provider_clean,
            "preço": price,
            "preço_fmt": format_brl(price),
            "duração_min": duration,
            "duração": _format_duration(duration),
            "escalas": int(q.stops or 0),
            "link": str(q.booking_link or ""),
            "score": v["viability_score"],
            "viabilidade": v["label"],
            "viabilidade_razoes": "; ".join(v["reasons"]),
            "preço_por_hora": price_per_hour,
            "preço_por_hora_fmt": (
                f"R$ {price_per_hour:_.2f}/h".replace(".", ",").replace("_", ".")
                if price_per_hour else "—"
            ),
            "ida": q.departure_date,
            "volta": q.return_date,
            "coletado_em": q.collected_at or q.detected_at,
            "milhas_est": int(price / 0.035) if price > 0 else 0,
            "is_demo": _is_demo(provider_clean),
        })

    return pd.DataFrame(rows), source_logs, run_logs


# ── Summary cards ─────────────────────────────────────────────────────────────

def _render_summary_cards(df: pd.DataFrame, source_logs: list, run_logs: list) -> None:
    last_run_dt: str = "—"
    if run_logs:
        last_run_dt = _format_date(run_logs[0].started_at)

    total = len(df)
    min_price = df["preço"].min() if total else None
    cheapest_airline = "—"
    best_pph = "—"
    best_route_label = "—"
    sources_with_error = []

    if total:
        cheapest_row = df.loc[df["preço"].idxmin()]
        cheapest_airline = cheapest_row["companhia"]

        real_df = df[~df["is_demo"]]
        if not real_df.empty:
            pph = real_df.dropna(subset=["preço_por_hora"])
            if not pph.empty:
                best_pph_row = pph.loc[pph["preço_por_hora"].idxmin()]
                best_pph = (
                    f"{best_pph_row['companhia']} — "
                    f"{best_pph_row['preço_por_hora_fmt']}"
                )
            best_score_row = real_df.loc[real_df["score"].idxmax()]
            best_route_label = (
                f"{best_score_row['origem']} → {best_score_row['destino']} "
                f"({best_score_row['companhia']}, {best_score_row['score']}/100)"
            )

    for sl in source_logs:
        if str(sl.status or "").startswith("fail"):
            if sl.source not in sources_with_error:
                sources_with_error.append(sl.source)

    error_label = ", ".join(sources_with_error) if sources_with_error else "Nenhuma"

    html = [
        '<div class="radar-overview-grid">',
        f'<div class="radar-card radar-mon"><div class="radar-card-label">Última execução</div>'
        f'<div class="radar-card-value" style="font-size:1rem">{last_run_dt}</div></div>',
        f'<div class="radar-card radar-rec"><div class="radar-card-label">Cotações via scraping</div>'
        f'<div class="radar-card-value">{total}</div></div>',
        f'<div class="radar-card radar-miles"><div class="radar-card-label">Menor preço encontrado</div>'
        f'<div class="radar-card-value">{format_brl(min_price) if min_price else "—"}</div></div>',
        f'<div class="radar-card radar-rec"><div class="radar-card-label">Companhia mais barata</div>'
        f'<div class="radar-card-value" style="font-size:1rem">{cheapest_airline}</div></div>',
        f'<div class="radar-card radar-mon"><div class="radar-card-label">Melhor preço/tempo</div>'
        f'<div class="radar-card-value" style="font-size:.9rem">{best_pph}</div></div>',
        f'<div class="radar-card radar-miles"><div class="radar-card-label">Melhor rota (score)</div>'
        f'<div class="radar-card-value" style="font-size:.85rem">{best_route_label}</div></div>',
        f'<div class="radar-card radar-rec"><div class="radar-card-label">Fontes com erro</div>'
        f'<div class="radar-card-value" style="font-size:.9rem;color:#F97316">{error_label}</div></div>',
        "</div>",
    ]
    st.markdown("".join(html), unsafe_allow_html=True)


# ── Filters ───────────────────────────────────────────────────────────────────

def _apply_filters(df: pd.DataFrame, search_id_filter: int | None = None) -> pd.DataFrame:
    if df.empty:
        return df

    col1, col2, col3 = st.columns(3)
    col4, col5, col6 = st.columns(3)

    origens = sorted(df["origem"].dropna().unique().tolist())
    destinos = sorted(df["destino"].dropna().unique().tolist())
    companhias = sorted(df["companhia"].dropna().unique().tolist())
    provedores = sorted(df["provedor"].dropna().unique().tolist())

    f_origem = col1.multiselect("Origem", origens, key="scr_f_origem")
    f_destino = col2.multiselect("Destino", destinos, key="scr_f_destino")
    f_companhia = col3.multiselect("Companhia", companhias, key="scr_f_companhia")
    f_provedor = col4.multiselect("Fonte/Scraper", provedores, key="scr_f_provedor")

    coletado_min = col5.date_input("Coleta a partir de", value=None, key="scr_f_data_min")
    incluir_demo = col6.toggle("Incluir dados demo/mock", value=False, key="scr_f_demo")

    filtered = df.copy()

    if not incluir_demo:
        filtered = filtered[~filtered["is_demo"]]
    if f_origem:
        filtered = filtered[filtered["origem"].isin(f_origem)]
    if f_destino:
        filtered = filtered[filtered["destino"].isin(f_destino)]
    if f_companhia:
        filtered = filtered[filtered["companhia"].isin(f_companhia)]
    if f_provedor:
        filtered = filtered[filtered["provedor"].isin(f_provedor)]
    if coletado_min:
        coletado_dt = pd.Timestamp(coletado_min, tz="UTC")
        col_dt = pd.to_datetime(filtered["coletado_em"], utc=True, errors="coerce")
        filtered = filtered[col_dt >= coletado_dt]
    if search_id_filter:
        filtered = filtered[filtered["search_id"] == search_id_filter]

    return filtered


# ── Main table ────────────────────────────────────────────────────────────────

def _render_table(df: pd.DataFrame) -> None:
    st.markdown("### Cotações capturadas via scraping")
    if df.empty:
        st.info("Nenhuma cotação encontrada com os filtros selecionados.")
        return

    display = df[[
        "coletado_em", "origem", "destino", "companhia", "preço_fmt",
        "duração", "escalas", "preço_por_hora_fmt", "score", "viabilidade",
        "provedor", "link",
    ]].copy()

    display["coletado_em"] = display["coletado_em"].map(_format_date)
    display.columns = [
        "Coletado em", "Origem", "Destino", "Companhia", "Preço",
        "Duração", "Escalas", "Preço/hora", "Score", "Viabilidade",
        "Fonte", "Link",
    ]
    st.dataframe(display, use_container_width=True, hide_index=True)


# ── Chart 1: Preço por companhia ──────────────────────────────────────────────

def _render_price_by_airline(df: pd.DataFrame) -> None:
    st.markdown("### Preço por companhia aérea")
    st.caption("Menor preço encontrado por companhia via scraping.")

    if df.empty or df["preço"].isna().all():
        st.info("Sem dados suficientes para este gráfico.")
        return

    agg = (
        df.dropna(subset=["preço"])
        .groupby("companhia", as_index=False)
        .agg(
            preço_min=("preço", "min"),
            duração=("duração", "first"),
            escalas=("escalas", "min"),
            milhas_est=("milhas_est", "first"),
            provedor=("provedor", "first"),
            coletado_em=("coletado_em", "max"),
        )
        .sort_values("preço_min")
    )

    min_price = agg["preço_min"].min()
    colors = [
        _AIRLINE_COLORS.get(row["companhia"], "#6366F1")
        if row["preço_min"] == min_price
        else f"{_AIRLINE_COLORS.get(row['companhia'], '#6366F1')}99"
        for _, row in agg.iterrows()
    ]

    fig = go.Figure(
        go.Bar(
            x=agg["companhia"].tolist(),
            y=agg["preço_min"].tolist(),
            marker_color=colors,
            text=[format_brl(v) for v in agg["preço_min"]],
            textposition="outside",
            customdata=list(zip(
                agg["duração"], agg["escalas"], agg["milhas_est"],
                agg["provedor"],
                [_format_date_short(v) for v in agg["coletado_em"]],
            )),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Preço: %{text}<br>"
                "Duração: %{customdata[0]}<br>"
                "Escalas: %{customdata[1]}<br>"
                "Milhas est.: %{customdata[2]:,.0f}<br>"
                "Fonte: %{customdata[3]}<br>"
                "Coletado: %{customdata[4]}"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        height=360,
        yaxis_title="Preço (R$)",
        xaxis_title="Companhia",
        margin=dict(l=8, r=8, t=20, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E2E8F0"),
    )
    fig.update_yaxes(tickprefix="R$ ", tickformat=",.0f", gridcolor="rgba(255,255,255,0.08)")
    st.plotly_chart(fig, use_container_width=True)

    best = agg.loc[agg["preço_min"].idxmin()]
    st.success(
        f"**Mais barato via scraping:** {best['companhia']} — "
        f"{format_brl(best['preço_min'])} "
        f"({best['duração']}, {best['escalas']} escala(s))"
    )


# ── Chart 2: Preço × Tempo ────────────────────────────────────────────────────

def _render_price_vs_time(df: pd.DataFrame) -> None:
    st.markdown("### Relação preço × tempo de viagem")
    st.caption(
        "Menor preço/hora por companhia — menor valor = melhor custo-benefício "
        "em tempo de viagem. Considere também o score de viabilidade."
    )

    pph_df = df.dropna(subset=["preço_por_hora"])
    if pph_df.empty:
        st.info("Sem dados de duração suficientes para este gráfico.")
        return

    agg = (
        pph_df.groupby("companhia", as_index=False)
        .agg(
            pph_min=("preço_por_hora", "min"),
            preço=("preço", "min"),
            duração_min=("duração_min", "first"),
            escalas=("escalas", "first"),
            score=("score", "max"),
        )
        .sort_values("pph_min")
    )
    agg["duração_h"] = agg["duração_min"] / 60
    agg["pph_fmt"] = agg["pph_min"].map(
        lambda v: f"R$ {v:_.2f}/h".replace(".", ",").replace("_", ".")
    )
    agg["preço_fmt"] = agg["preço"].map(format_brl)

    fig = px.bar(
        agg,
        x="companhia",
        y="pph_min",
        color="companhia",
        color_discrete_map=_AIRLINE_COLORS,
        text="pph_fmt",
        custom_data=["preço_fmt", "duração_h", "escalas", "score"],
        labels={"pph_min": "R$/hora de voo", "companhia": "Companhia"},
    )
    fig.update_traces(
        textposition="outside",
        hovertemplate=(
            "<b>%{x}</b><br>"
            "R$/hora: %{text}<br>"
            "Preço: %{customdata[0]}<br>"
            "Duração: %{customdata[1]:.1f}h<br>"
            "Escalas: %{customdata[2]}<br>"
            "Score: %{customdata[3]}/100"
            "<extra></extra>"
        ),
    )
    fig.update_layout(
        height=360,
        yaxis_title="R$ por hora de voo",
        margin=dict(l=8, r=8, t=20, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E2E8F0"),
        showlegend=False,
    )
    fig.update_yaxes(tickprefix="R$ ", tickformat=",.2f", gridcolor="rgba(255,255,255,0.08)")
    st.plotly_chart(fig, use_container_width=True)

    best = agg.loc[agg["pph_min"].idxmin()]
    st.info(
        f"**Melhor custo-benefício em tempo:** {best['companhia']} — "
        f"{best['pph_fmt']} "
        f"(preço: {best['preço_fmt']}, duração: {best['duração_h']:.1f}h, score: {int(best['score'])}/100)"
    )


# ── Chart 3: Score de viabilidade ─────────────────────────────────────────────

def _render_viability_chart(df: pd.DataFrame) -> None:
    st.markdown("### Score de viabilidade por companhia")
    st.caption(
        "Score 0-100 combinando preço, duração, escalas, fonte e link. "
        "Maior score = rota mais viável."
    )

    if df.empty:
        st.info("Sem dados para o gráfico de viabilidade.")
        return

    agg = (
        df.groupby("companhia", as_index=False)
        .agg(
            score_max=("score", "max"),
            score_med=("score", "mean"),
            viabilidade=("viabilidade", "first"),
            preço_min=("preço", "min"),
            escalas_min=("escalas", "min"),
        )
        .sort_values("score_max", ascending=False)
    )
    agg["preço_fmt"] = agg["preço_min"].map(format_brl)
    agg["score_med"] = agg["score_med"].round(1)

    fig = px.bar(
        agg,
        x="companhia",
        y="score_max",
        color="companhia",
        color_discrete_map=_AIRLINE_COLORS,
        text="score_max",
        custom_data=["viabilidade", "preço_fmt", "escalas_min", "score_med"],
        labels={"score_max": "Score de viabilidade", "companhia": "Companhia"},
    )
    fig.update_traces(
        texttemplate="%{text}/100",
        textposition="outside",
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Score: %{y}/100<br>"
            "Classificação: %{customdata[0]}<br>"
            "Menor preço: %{customdata[1]}<br>"
            "Escalas mín.: %{customdata[2]}<br>"
            "Score médio: %{customdata[3]}"
            "<extra></extra>"
        ),
    )
    fig.update_layout(
        height=360,
        yaxis=dict(range=[0, 110], title="Score (0-100)"),
        margin=dict(l=8, r=8, t=20, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E2E8F0"),
        showlegend=False,
    )
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.08)")
    st.plotly_chart(fig, use_container_width=True)

    best = agg.loc[agg["score_max"].idxmax()]
    st.success(
        f"**Melhor rota (score {int(best['score_max'])}/100):** {best['companhia']} — "
        f"{best['viabilidade']} — menor preço: {best['preço_fmt']}"
    )


# ── Best route card ───────────────────────────────────────────────────────────

def _render_best_route(df: pd.DataFrame, dest_filter: str = "") -> None:
    real_df = df[~df["is_demo"]]
    if dest_filter:
        real_df = real_df[real_df["destino"].str.upper() == dest_filter.upper()]
    if real_df.empty:
        return

    best = real_df.loc[real_df["score"].idxmax()]
    link_html = (
        f'<a href="{best["link"]}" target="_blank" style="color:#38BDF8">Abrir link →</a>'
        if str(best["link"]).startswith("http") else "—"
    )
    st.markdown(
        f"""
        <div style="border:1px solid #334155;border-radius:10px;padding:16px;
                    background:linear-gradient(135deg,#0F172A 60%,#1E293B);
                    margin-bottom:16px">
          <div style="font-size:.75rem;color:#94A3B8;margin-bottom:4px">
            Rota mais viável {f"para {dest_filter}" if dest_filter else "encontrada"}
          </div>
          <div style="font-size:1.3rem;font-weight:700;color:#F1F5F9">
            {best["origem"]} → {best["destino"]}
          </div>
          <div style="font-size:1.1rem;color:#2DD4BF;margin:4px 0">
            {best["companhia"]} — {best["preço_fmt"]}
          </div>
          <div style="font-size:.85rem;color:#94A3B8">
            Duração: {best["duração"]} · Escalas: {best["escalas"]} ·
            Score: {int(best["score"])}/100 ({best["viabilidade"]}) ·
            Fonte: {best["provedor"]} · {link_html}
          </div>
          <div style="font-size:.8rem;color:#64748B;margin-top:6px">
            {best.get("viabilidade_razoes", "")}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Diagnostics (no real scraping data yet) ───────────────────────────────────

def _render_no_data_diagnostic(source_logs: list, run_logs: list) -> None:
    from app.settings import get_settings
    settings = get_settings()

    st.warning("Nenhum dado real de scraping foi encontrado no banco.")

    last_run = _format_date(run_logs[0].started_at) if run_logs else "Indisponivel"

    # IMPORTANTE: settings.enable_airline_scrapers le o ambiente do Streamlit Cloud,
    # NAO do GitHub Actions. Sao secrets separados e independentes.
    # Prova de que o GitHub Actions tem o secret certo: se o step
    # "Install Playwright browser" aparece nos logs do Actions, o secret esta true.
    diag = {
        "Scraping implementado": "Sim (5 scrapers: Copa Air, Azul, GOL, LATAM, Google Flights)",
        "GitHub Actions configurado": "Sim (monitor.yml, a cada 30 min)",
        "Ultima execucao registrada": last_run,
        "Tabela de destino": "flight_quotes (provider = copa_air/azul/gol/latam/google_flights)",
        "Nota": (
            "Se 'Install Playwright browser' aparece nos logs do Actions, "
            "ENABLE_AIRLINE_SCRAPERS=true esta ativo la."
        ),
    }
    for k, v in diag.items():
        st.markdown(
            f'<div class="status-row">'
            f'<span class="status-label">{k}</span>'
            f'<span class="status-value">{v}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.info(
        "**Scrapers estao habilitados no GitHub Actions** (Playwright instalou = secret true). "
        "Os scrapers rodaram mas retornaram 0 cotacoes. Causas mais comuns:\n\n"
        "1. **Bloqueio anti-bot** — Azul/GOL/LATAM/Google bloqueiam IPs de datacenter com "
        "captcha ou 403. Isso e esperado. **Copa Air** tem robots.txt aberto e e a fonte "
        "com mais chance de funcionar.\n"
        "2. **Busca expirada** — se a data de ida ja passou, o worker ignora a busca. "
        "Verifique em Controle de Buscas se ha busca ativa com data futura.\n"
        "3. **Parser desatualizado** — os sites mudam o HTML frequentemente; o seletor "
        "pode nao estar encontrando os precos na pagina atual."
    )

    if source_logs:
        st.markdown("**Ultimas tentativas de coleta (source_logs):**")
        log_df = pd.DataFrame([
            {"Fonte": s.source, "Status": s.status,
             "Mensagem": (s.message or "")[:120], "Quando": _format_date(s.created_at)}
            for s in source_logs
        ])
        st.dataframe(log_df, use_container_width=True, hide_index=True)


# ── Main render function ───────────────────────────────────────────────────────

def render_scraping_tab(search_id_filter: int | None = None) -> None:
    """Render the full 'Radar Scraping' tab.

    ``search_id_filter`` is optionally set by the Controle de Buscas tab when
    the user clicks 'Ver dados de scraping desta busca'.
    """
    st.subheader("📡 Radar Scraping")
    st.caption(
        "Cotacoes capturadas via scraping (Copa Air, Azul, GOL, LATAM, Google Flights) "
        "pelo GitHub Actions. Requer ENABLE_AIRLINE_SCRAPERS=true nos Secrets."
    )

    try:
        df, source_logs, run_logs = _load_scraping_data()
    except Exception as exc:
        st.error(f"Erro ao carregar dados de scraping: {exc}")
        return

    if search_id_filter:
        st.info(f"Filtrando cotações de scraping para a busca #{search_id_filter}. "
                "Remova o filtro clicando no botão abaixo.")
        if st.button("Remover filtro de busca", key="scr_clear_search_filter"):
            st.session_state.pop("scraping_filter_search_id", None)
            st.rerun()

    # ── Summary ──────────────────────────────────────────────────────────────
    real_df = df[~df["is_demo"]] if not df.empty else df
    _render_summary_cards(real_df, source_logs, run_logs)

    st.divider()

    if df.empty:
        _render_no_data_diagnostic(source_logs, run_logs)
        return

    # ── Filters ──────────────────────────────────────────────────────────────
    with st.expander("Filtros", expanded=True):
        filtered = _apply_filters(df, search_id_filter=search_id_filter)

    real_filtered = filtered[~filtered["is_demo"]]

    # Show demo badge if demo data included
    demo_count = int(filtered["is_demo"].sum())
    if demo_count > 0:
        st.markdown(
            f'<span style="background:#92400E;color:#FEF3C7;padding:2px 10px;'
            f'border-radius:999px;font-size:.78rem">'
            f'{demo_count} cotacao(oes) de demonstracao incluidas</span>',
            unsafe_allow_html=True,
        )

    # ── Best route card ──────────────────────────────────────────────────────
    dest_values = real_filtered["destino"].unique().tolist() if not real_filtered.empty else []
    dest_sel = dest_values[0] if len(dest_values) == 1 else ""

    if not real_filtered.empty:
        _render_best_route(real_filtered, dest_filter=dest_sel)

    # ── Table ────────────────────────────────────────────────────────────────
    _render_table(filtered)

    st.divider()

    # ── Charts ───────────────────────────────────────────────────────────────
    if real_filtered.empty:
        st.info("Sem cotacoes reais para gerar os graficos. Habilite scrapers ou aguarde a proxima execucao do worker.")
        return

    c1, c2 = st.columns(2)
    with c1:
        _render_price_by_airline(real_filtered)
    with c2:
        _render_viability_chart(real_filtered)

    st.divider()
    _render_price_vs_time(real_filtered)

    # ── Viability ranking ────────────────────────────────────────────────────
    if not real_filtered.empty:
        st.divider()
        st.markdown("### Ranking de viabilidade por cotação")
        st.caption("Top 10 cotações com maior score de viabilidade.")
        top_rows = (
            real_filtered
            .sort_values("score", ascending=False)
            .head(10)[[
                "origem", "destino", "companhia", "preço_fmt",
                "duração", "escalas", "preço_por_hora_fmt",
                "score", "viabilidade", "provedor",
            ]]
            .copy()
        )
        top_rows.columns = [
            "Origem", "Destino", "Companhia", "Preço",
            "Duração", "Escalas", "Preço/hora",
            "Score", "Viabilidade", "Fonte",
        ]
        st.dataframe(top_rows, use_container_width=True, hide_index=True)

    # ── Source logs ──────────────────────────────────────────────────────────
    if source_logs:
        with st.expander("Historico de execucoes por fonte (source_logs)"):
            log_df = pd.DataFrame([
                {
                    "Fonte": s.source,
                    "Status": s.status,
                    "Mensagem": (s.message or "")[:160],
                    "Quando": _format_date(s.created_at),
                }
                for s in source_logs
            ])
            st.dataframe(log_df, use_container_width=True, hide_index=True)
