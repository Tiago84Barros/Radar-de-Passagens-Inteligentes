from __future__ import annotations

import random
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from services.miles_service import estimate_miles, format_miles
from utils.formatters import format_brl, format_duration_short, format_stops

_TEAL = "#2DD4BF"
_MUTED_BAR = "#3b5168"
_PLOT_LAYOUT = dict(
    height=400,
    margin=dict(l=8, r=8, t=30, b=8),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#E5EDF8"),
)


def render_current_prices_bar(deals: list[dict]) -> None:
    """Bar chart: current price per airline. Cheapest bar highlighted in teal."""
    if not deals:
        return
    rows = []
    for d in deals:
        price = float(d.get("price_brl") or 0)
        if price <= 0:
            continue
        name, _ = _airline_name(d)
        rows.append(
            {
                "Companhia": name,
                "Preço": price,
                "Milhas": format_miles(d.get("estimated_miles") or estimate_miles(price)),
                "Tempo": format_duration_short(d.get("duration_minutes")) or "—",
                "Escalas": format_stops(d.get("stops")) or "—",
                "PreçoFmt": format_brl(price),
            }
        )
    if not rows:
        return
    df = pd.DataFrame(rows).sort_values("Preço")
    cheapest = df["Preço"].min()
    colors = [_TEAL if p == cheapest else _MUTED_BAR for p in df["Preço"]]

    st.markdown(
        '<div class="deals-section-header">📊 Comparação de preços por companhia</div>',
        unsafe_allow_html=True,
    )
    fig = go.Figure(
        go.Bar(
            x=df["Companhia"],
            y=df["Preço"],
            marker_color=colors,
            customdata=df[["PreçoFmt", "Milhas", "Tempo", "Escalas"]].values,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Preço: %{customdata[0]}<br>"
                "Milhas est.: %{customdata[1]}<br>"
                "Tempo total: %{customdata[2]}<br>"
                "Escalas: %{customdata[3]}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **_PLOT_LAYOUT,
        yaxis_title="Preço (R$)",
        xaxis_title="",
    )
    fig.update_yaxes(gridcolor="rgba(148,163,184,.15)")
    st.plotly_chart(fig, use_container_width=True)


def render_future_projection(
    df_quotes: pd.DataFrame,
    origin: str,
    destination: str,
    fallback_base_price: float | None = None,
) -> None:
    """Bar chart: lowest future fares per airline across the next 12 months.

    Uses real future quotes when available; otherwise renders a clearly-labelled
    simulation so the section is never empty."""
    st.markdown(
        '<div class="deals-section-header">🔮 Próximas oportunidades para esta rota</div>',
        unsafe_allow_html=True,
    )

    o = (origin or "").upper()
    d = (destination or "").upper()
    real = _real_future_data(df_quotes, o, d)

    if real is not None and not real.empty:
        st.markdown(
            '<p class="deals-section-subtitle">Menores tarifas futuras já coletadas, '
            'por mês e companhia (próximos 12 meses).</p>',
            unsafe_allow_html=True,
        )
        chart_df = real
        simulated = False
    else:
        chart_df = _demo_future_data(o, d, fallback_base_price)
        simulated = True
        st.markdown(
            '<p class="deals-section-subtitle">⚠️ <strong>Simulação</strong> — ainda não há '
            'cotações futuras reais para esta rota. Os valores abaixo são estimados e serão '
            'substituídos pelos dados reais conforme o radar coletar.</p>',
            unsafe_allow_html=True,
        )

    chart_df = chart_df.copy()
    chart_df["MilhasFmt"] = chart_df["Preço"].apply(lambda p: format_miles(estimate_miles(float(p))))
    chart_df["PreçoFmt"] = chart_df["Preço"].apply(format_brl)
    chart_df["Rota"] = f"{o} → {d}"

    fig = px.bar(
        chart_df,
        x="Mês",
        y="Preço",
        color="Companhia",
        barmode="group",
        custom_data=["Companhia", "PreçoFmt", "MilhasFmt", "Rota"],
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Mês: %{x}<br>"
            "Preço: %{customdata[1]}<br>"
            "Milhas est.: %{customdata[2]}<br>"
            "Rota: %{customdata[3]}<extra></extra>"
        )
    )
    layout = dict(_PLOT_LAYOUT)
    layout["height"] = 420
    fig.update_layout(**layout, yaxis_title="Preço (R$)", xaxis_title="", legend_title="Companhia")
    fig.update_yaxes(gridcolor="rgba(148,163,184,.15)")
    if simulated:
        fig.update_layout(title=dict(text="Simulação", font=dict(color="#FBBF24", size=13), x=0.01))
    st.plotly_chart(fig, use_container_width=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _airline_name(deal: dict) -> tuple[str, str]:
    from components.cards import _airline_visual

    return _airline_visual(str(deal.get("airline") or ""))


def _real_future_data(df_quotes: pd.DataFrame, origin: str, destination: str) -> pd.DataFrame | None:
    if df_quotes is None or df_quotes.empty or "preço" not in df_quotes.columns:
        return None
    route = df_quotes[
        (df_quotes["origem"].astype(str).str.upper() == origin)
        & (df_quotes["destino"].astype(str).str.upper() == destination)
    ].copy()
    if route.empty:
        return None
    route["ida_dt"] = pd.to_datetime(route["ida"], errors="coerce")
    today = pd.Timestamp(date.today())
    one_year = today + pd.Timedelta(days=365)
    route = route.dropna(subset=["ida_dt", "preço"])
    route = route[(route["ida_dt"] >= today) & (route["ida_dt"] <= one_year)]
    route = route[route["preço"] > 0]
    if route.empty:
        return None
    route["companhia"] = route["companhia"].fillna("Não informada").replace("", "Não informada")
    route["Mês"] = route["ida_dt"].dt.strftime("%m/%Y")
    grouped = (
        route.groupby(["Mês", "companhia"], as_index=False)["preço"].min()
        .rename(columns={"companhia": "Companhia", "preço": "Preço"})
    )
    # Sort months chronologically
    grouped["_sort"] = pd.to_datetime("01/" + grouped["Mês"], format="%d/%m/%Y", errors="coerce")
    grouped = grouped.sort_values("_sort").drop(columns="_sort")
    return grouped


def _demo_future_data(origin: str, destination: str, base_price: float | None) -> pd.DataFrame:
    base = float(base_price) if base_price and base_price > 0 else 1200.0
    airlines = ["LATAM", "GOL", "Azul"]
    rng = random.Random(f"{origin}{destination}")
    today = date.today()
    rows = []
    for i in range(0, 12, 2):  # one bar every 2 months → 6 points
        month = (today.month - 1 + i) % 12 + 1
        year = today.year + (today.month - 1 + i) // 12
        label = f"{month:02d}/{year}"
        for airline in airlines:
            factor = rng.uniform(0.78, 1.35)
            rows.append({"Mês": label, "Companhia": airline, "Preço": round(base * factor, 2)})
    return pd.DataFrame(rows)
