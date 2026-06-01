"""UI for the decision radar: recommendation headline, radar overview KPIs and
destination opportunity cards. Renders the decision-engine output produced by
``services.decision_engine`` / ``services.multi_destination_adapter``.
"""
from __future__ import annotations

import streamlit as st

from services.decision_engine import (
    REC_BUY,
    REC_CASH,
    REC_COMMON,
    REC_IGNORE,
    REC_MILES,
    REC_MONITOR,
    REC_WAIT,
)
from services.miles_service import MILES_DISCLAIMER, cents_per_mile_label
from utils.formatters import (
    estimate_miles,
    format_brl,
    format_date_br,
    format_duration_short,
    format_miles,
    format_stops,
)

# Recommendation → (css modifier, emoji). Drives the colored badge/border.
_REC_STYLE = {
    REC_BUY: ("buy", "🟢"),
    REC_MILES: ("miles", "🏆"),
    REC_MONITOR: ("monitor", "🟡"),
    REC_CASH: ("cash", "💵"),
    REC_COMMON: ("monitor", "⚪"),
    REC_WAIT: ("wait", "⏳"),
    REC_IGNORE: ("wait", "🚫"),
}


def _rec_style(recommendation: str) -> tuple[str, str]:
    return _REC_STYLE.get(recommendation, ("monitor", "🔍"))


def render_decision_summary(rec: dict, *, consider_miles: bool = True) -> None:
    """Headline 'Recomendação do sistema' card plus best cash/best miles options."""
    if not rec:
        return
    recommendation = rec.get("recommendation", REC_MONITOR)
    mod, emoji = _rec_style(recommendation)
    confidence = int(rec.get("confidence") or 0)
    main_reason = rec.get("main_reason") or ""
    supporting = rec.get("supporting_reasons") or []

    reasons_html = "".join(f"<li>{r}</li>" for r in supporting[:4])
    st.markdown(
        f'<div class="decision-hero decision-{mod}">'
        f'<div class="decision-hero-top">'
        f'<span class="decision-hero-kicker">Recomendação do sistema</span>'
        f'<span class="decision-hero-confidence">Confiança {confidence}/100</span>'
        f'</div>'
        f'<div class="decision-hero-verdict">{emoji} {recommendation}</div>'
        f'<div class="decision-hero-reason">{main_reason}</div>'
        f'<ul class="decision-hero-reasons">{reasons_html}</ul>'
        f'</div>',
        unsafe_allow_html=True,
    )

    cash = rec.get("best_cash_option")
    miles = rec.get("best_miles_option")
    cols = st.columns(2) if consider_miles else st.columns(1)
    with cols[0]:
        _render_option_card("💵 Melhor opção em dinheiro", cash, kind="cash")
    if consider_miles:
        with cols[1]:
            _render_option_card("🏆 Melhor opção em milhas", miles, kind="miles")
        st.caption(f"ℹ️ {MILES_DISCLAIMER}")


def _render_option_card(title: str, opt: dict | None, *, kind: str) -> None:
    if not opt:
        st.markdown(
            f'<div class="option-card option-{kind} option-empty">'
            f'<div class="option-card-title">{title}</div>'
            f'<div class="option-card-empty">Sem dados ainda.</div></div>',
            unsafe_allow_html=True,
        )
        return
    from data.airlines_catalog import get_airline_name

    price = float(opt.get("price_brl") or 0)
    airline = get_airline_name(opt.get("airline")) if opt.get("airline") else "—"
    provider = opt.get("provider") or "—"
    miles = int(opt.get("estimated_miles") or 0)
    mile_value = float(opt.get("mile_value") or 0)
    meta_bits = []
    dur = format_duration_short(opt.get("duration_minutes"))
    stops = format_stops(opt.get("stops"))
    if dur:
        meta_bits.append(f"⏱ {dur}")
    if stops:
        meta_bits.append(stops)
    meta = " · ".join(meta_bits) if meta_bits else ""

    if kind == "miles":
        headline = format_miles(miles)
        sub = (
            f"≈ {format_brl(price)} · cada milha vale "
            f"{cents_per_mile_label(mile_value)}" if mile_value else f"≈ {format_brl(price)}"
        )
    else:
        headline = format_brl(price)
        sub = f"≈ {format_miles(miles)} estimadas" if miles else ""

    st.markdown(
        f'<div class="option-card option-{kind}">'
        f'<div class="option-card-title">{title}</div>'
        f'<div class="option-card-value">{headline}</div>'
        f'<div class="option-card-sub">{sub}</div>'
        f'<div class="option-card-meta">{airline} · {provider}{(" · " + meta) if meta else ""}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_search_summary(deals: list[dict], rec: dict | None, *, route: str, progress: dict | None = None) -> None:
    """Compact 'resumo da busca' card shown after a search: route, cheapest price,
    estimated miles, best airline (full name), all airlines found (full names),
    provider, recommendation, total time and worker status."""
    from data.airlines_catalog import get_airline_info, get_airline_name

    from utils.formatters import format_collected_age

    valid = [d for d in (deals or []) if float(d.get("price_brl") or 0) > 0]
    if not valid:
        return
    cheapest = min(valid, key=lambda d: float(d.get("price_brl") or 0))
    price = float(cheapest.get("price_brl") or 0)
    miles = int(cheapest.get("estimated_miles") or estimate_miles(price))
    best_info = get_airline_info(cheapest.get("airline"))
    best_airline = best_info["name"]
    best_logo = (
        f'<img src="{best_info["logo_url"]}" alt="{best_airline}" class="summary-logo" '
        f'onerror="this.style.display=&#39;none&#39;">' if best_info.get("logo_url") else "✈️ "
    )
    provider = cheapest.get("provider") or "—"

    # Most recent quote timestamp ("há X") + how many options were found.
    ages = [d.get("collected_at") for d in valid if d.get("collected_at")]
    recent_age = ""
    if ages:
        recent_age = format_collected_age(max(ages))
    options_count = len(valid)

    # Distinct airlines found, full names, cheapest-first.
    seen, airlines = set(), []
    for d in sorted(valid, key=lambda d: float(d.get("price_brl") or 0)):
        name = get_airline_name(d.get("airline"))
        if name not in seen:
            seen.add(name)
            airlines.append(name)

    recommendation = (rec or {}).get("recommendation", "—")
    mod, emoji = _rec_style(recommendation)

    total_time = ""
    worker_html = ""
    if progress:
        total_time = f"{float(progress.get('api_seconds') or 0):.1f}s"
        ws = progress.get("worker_status")
        ws_label = {
            "queued": "⏳ na fila", "in_progress": "🔄 em execução",
            "completed": "✅ concluído", "failed": "❌ falhou",
            "not_configured": "➖ não configurado",
        }.get(ws, "")
        if ws_label:
            worker_html = f'<div class="summary-row"><span>Worker</span><b>{ws_label}</b></div>'

    rows = [
        ("Rota", route or "—"),
        ("Menor preço", format_brl(price)),
        ("Milhas estimadas", format_miles(miles)),
        ("Melhor companhia", f'{best_logo}{best_airline}'),
        ("Opções encontradas", str(options_count)),
        ("Fonte", provider),
        ("Recomendação", f"{emoji} {recommendation}"),
    ]
    if recent_age:
        rows.append(("Cotação mais recente", recent_age))
    if total_time:
        rows.append(("Tempo da busca (API)", total_time))
    rows_html = "".join(f'<div class="summary-row"><span>{k}</span><b>{v}</b></div>' for k, v in rows)

    st.markdown(
        f'<div class="search-summary search-summary-{mod}">'
        f'<div class="search-summary-title">🧾 Resumo da busca</div>'
        f'{rows_html}{worker_html}'
        f'<div class="summary-airlines"><span>Companhias encontradas:</span> {", ".join(airlines)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_radar_overview(metrics: dict) -> None:
    """The 'Radar de decisão' KPI strip: best cash, best miles, best national,
    best international, recommendation and monitoring status.

    ``metrics`` is a plain dict (computed in the app) so this stays presentation
    only:
        best_cash, best_cash_sub, best_miles, best_miles_sub, best_national,
        best_national_sub, best_international, best_international_sub,
        recommendation, recommendation_sub, monitor, monitor_sub
    """
    st.markdown(
        '<div class="deals-section-header">🛰️ Radar de decisão</div>',
        unsafe_allow_html=True,
    )
    cards = [
        ("💵 Melhor preço em dinheiro", metrics.get("best_cash"), metrics.get("best_cash_sub"), "cash"),
        ("🏆 Melhor alternativa em milhas", metrics.get("best_miles"), metrics.get("best_miles_sub"), "miles"),
        ("🇧🇷 Melhor destino nacional", metrics.get("best_national"), metrics.get("best_national_sub"), "nat"),
        ("🌎 Melhor destino internacional", metrics.get("best_international"), metrics.get("best_international_sub"), "intl"),
        ("🧭 Recomendação", metrics.get("recommendation"), metrics.get("recommendation_sub"), "rec"),
        ("📡 Monitoramento", metrics.get("monitor"), metrics.get("monitor_sub"), "mon"),
    ]
    html = ['<div class="radar-overview-grid">']
    for title, value, sub, mod in cards:
        html.append(
            f'<div class="radar-card radar-{mod}">'
            f'<div class="radar-card-label">{title}</div>'
            f'<div class="radar-card-value">{value or "—"}</div>'
            f'<div class="radar-card-sub">{sub or ""}</div>'
            f'</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def render_opportunity_cards(
    opportunities: list[dict],
    *,
    title: str,
    key_prefix: str,
    on_monitor=None,
) -> None:
    """Render a ranked list of destination opportunities (postcard cards) with a
    'Monitorar este destino' button on each. ``on_monitor(opp)`` is called when a
    button is clicked."""
    if not opportunities:
        st.markdown(
            f'<div class="deals-section-subtitle">{title}: nenhum resultado nesta categoria ainda.</div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown(f'<div class="opp-group-title">{title}</div>', unsafe_allow_html=True)

    per_row = 3
    for start in range(0, len(opportunities), per_row):
        chunk = opportunities[start:start + per_row]
        cols = st.columns(len(chunk))
        for i, opp in enumerate(chunk):
            with cols[i]:
                st.markdown(_opportunity_card_html(opp), unsafe_allow_html=True)
                idx = start + i
                if st.button(
                    "🛰️ Monitorar este destino",
                    key=f"{key_prefix}_mon_{idx}_{opp.get('destination_iata','')}",
                    use_container_width=True,
                ):
                    if on_monitor:
                        on_monitor(opp)


def _opportunity_card_html(opp: dict) -> str:
    iata = str(opp.get("destination_iata") or "").upper()
    city = opp.get("destination_city") or iata
    country = opp.get("destination_country") or ""
    price = float(opp.get("cash_price") or 0)
    miles = int(opp.get("estimated_miles") or 0)
    score = int(opp.get("score") or 0)
    rec = opp.get("recommendation") or REC_MONITOR
    mod, emoji = _rec_style(rec)
    image = opp.get("image_url") or ""
    gradient = opp.get("gradient") or "linear-gradient(135deg,#0d3b2e,#07263a)"
    when = format_date_br(opp.get("departure_date"))
    source = opp.get("source") or "—"
    demo_tag = '<span class="opp-demo">demo</span>' if opp.get("is_demo") else ""

    if image:
        bg = (
            f"linear-gradient(180deg,rgba(8,17,31,.15) 0%,rgba(8,17,31,.78) 62%,"
            f"rgba(8,17,31,.96) 100%), url({image}), {gradient}"
        )
    else:
        bg = f"linear-gradient(180deg,rgba(8,17,31,.4) 0%,rgba(8,17,31,.94) 100%), {gradient}"

    # Geographic badges: Nacional/Internacional · region/continent · IATA.
    is_national = (opp.get("destination_type") == "national")
    type_label = "Nacional" if is_national else "Internacional"
    type_cls = "geo-nat" if is_national else "geo-intl"
    region = opp.get("region") or ("Brasil" if is_national else "Exterior")
    geo_badges = (
        f'<div class="opp-geo-badges">'
        f'<span class="geo-badge {type_cls}">{type_label}</span>'
        f'<span class="geo-badge geo-region">{region}</span>'
        f'<span class="geo-badge geo-iata">{iata}</span>'
        f'</div>'
    )

    cid = f"opp-{iata}-{int(price)}"
    return (
        f"<style>#{cid}{{background-image:{bg};}}</style>"
        f'<div id="{cid}" class="opp-card">'
        f'<div class="opp-card-overlay">'
        f'<span class="opp-badge opp-badge-{mod}">{emoji} {rec}</span>'
        f'<div class="opp-card-code">{iata} {demo_tag}</div>'
        f'<div class="opp-card-city">{city}</div>'
        f'<div class="opp-card-country">{country}</div>'
        f'{geo_badges}'
        f'<div class="opp-card-price">{format_brl(price)}</div>'
        f'<div class="opp-card-miles">≈ {format_miles(miles)} estimadas</div>'
        f'<div class="opp-card-meta">📅 {when} · Score {score}/100 · {source}</div>'
        f'</div></div>'
    )
