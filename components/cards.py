from __future__ import annotations

from datetime import date

import streamlit as st

from services.miles_service import format_miles


# ─── classification → visual mapping ─────────────────────────────────────────

_CLASSIFICATION_CSS: dict[str, str] = {
    "excelente oportunidade": "badge-excellent",
    "Excelente oportunidade": "badge-excellent",
    "otima oportunidade": "badge-great",
    "ótima oportunidade": "badge-great",
    "Ótima oportunidade": "badge-great",
    "boa oportunidade": "badge-good",
    "Boa oportunidade": "badge-good",
}

_CLASSIFICATION_LABEL: dict[str, str] = {
    "excelente oportunidade": "Excelente",
    "Excelente oportunidade": "Excelente",
    "otima oportunidade": "Ótima",
    "ótima oportunidade": "Ótima",
    "Ótima oportunidade": "Ótima",
    "boa oportunidade": "Boa",
    "Boa oportunidade": "Boa",
}

_SCORE_THRESHOLDS = [
    (85, "badge-excellent", "Excelente"),
    (70, "badge-great", "Ótima"),
    (55, "badge-good", "Boa"),
    (0, "badge-muted", "Normal"),
]


def _classification_info(classification: str, score: int) -> tuple[str, str]:
    """Return (css_class, label) for a classification string or score."""
    cls_lower = (classification or "").lower().strip()
    for key, css in _CLASSIFICATION_CSS.items():
        if key.lower() in cls_lower:
            label = _CLASSIFICATION_LABEL.get(key, classification)
            return css, label
    # Fall back to score
    for threshold, css, label in _SCORE_THRESHOLDS:
        if score >= threshold:
            return css, label
    return "badge-muted", "Normal"


def _fmt_date(d) -> str:
    if d is None:
        return "–"
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    try:
        import pandas as pd
        parsed = pd.to_datetime(d)
        return parsed.strftime("%d/%m/%Y")
    except Exception:
        return str(d)


def _fmt_brl(value: float) -> str:
    """Format as R$ 1.234,56"""
    if not value:
        return "–"
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _date_range_label(departure: date | None, return_date: date | None) -> str:
    if departure and return_date:
        return f"{_fmt_date(departure)} a {_fmt_date(return_date)}"
    if departure:
        return _fmt_date(departure)
    return "Data a confirmar"


def _build_card_html(deal: dict) -> str:
    """Generate HTML for a single deal card."""
    score = int(deal.get("score") or 0)
    classification = str(deal.get("classification") or "")
    cls_css, cls_label = _classification_info(classification, score)

    category = deal.get("category", "national")
    cat_css = "badge-national" if category == "national" else "badge-intl"
    cat_label = "Nacional" if category == "national" else "Internacional"

    origin_city = deal.get("origin_city") or deal.get("origin_iata") or "–"
    origin_iata = deal.get("origin_iata") or ""
    dest_city = deal.get("destination_city") or deal.get("destination_iata") or "–"
    dest_iata = deal.get("destination_iata") or ""
    dest_country = deal.get("destination_country") or ""

    departure = deal.get("departure_date")
    return_date = deal.get("return_date")
    date_label = _date_range_label(departure, return_date)

    price = float(deal.get("price_brl") or 0)
    price_label = _fmt_brl(price)

    miles = deal.get("estimated_miles") or 0
    miles_label = format_miles(miles)

    airline = deal.get("airline") or "–"
    provider = deal.get("provider") or ""
    booking_link = deal.get("booking_link") or "#"
    is_demo = bool(deal.get("is_demo"))
    via_hub = str(deal.get("via_hub") or "")
    is_combined = bool(via_hub)

    image_url = deal.get("image_url") or ""
    gradient = deal.get("gradient") or "linear-gradient(135deg,#0d3b2e,#07263a)"

    # Build background: gradient overlay + image (image loads behind gradient)
    if image_url:
        bg = (
            f"linear-gradient(180deg,rgba(8,17,31,.05) 0%,rgba(8,17,31,.75) 65%,"
            f"rgba(8,17,31,.95) 100%), url('{image_url}'), {gradient}"
        )
    else:
        bg = f"linear-gradient(180deg,rgba(8,17,31,.30) 0%,rgba(8,17,31,.92) 100%), {gradient}"

    demo_badge = (
        '<span class="deal-badge badge-demo">Modo Demo</span>'
        if is_demo else ""
    )
    connection_badge = (
        f'<span class="deal-badge badge-connection">via {via_hub}</span>'
        if is_combined else ""
    )

    # Route display: show intermediate hub if combined
    if is_combined:
        route_display = f"{origin_iata} → {via_hub} → {dest_iata}"
        route_iata = f"{origin_city} → {via_hub} → {dest_city}"
        combined_note = (
            '<div class="deal-card-combined-note">'
            '⚠️ Soma de dois trechos — reserve cada trecho individualmente.'
            '</div>'
        )
    else:
        route_display = f"{origin_city} → {dest_city}"
        route_iata = f"{origin_iata} → {dest_iata}"
        combined_note = ""

    link_btn = (
        f'<a class="deal-card-btn" href="{booking_link}" target="_blank" rel="noopener">Ver detalhes →</a>'
        if not is_demo and booking_link and booking_link != "#"
        else f'<a class="deal-card-btn deal-card-btn-demo" href="https://www.google.com/flights" target="_blank" rel="noopener">Buscar voo →</a>'
    )

    dest_country_html = (
        f'<div class="deal-card-country">{dest_country}</div>'
        if dest_country else ""
    )

    return f"""
<div class="deal-card">
  <div class="deal-card-header" style="background-image:{bg};background-color:#0d1e30;background-size:cover;background-position:center;">
    <div class="deal-card-header-top">
      <span class="deal-badge {cat_css}">{cat_label}</span>
      <span class="deal-badge {cls_css}">{cls_label}</span>
      {connection_badge}
      {demo_badge}
    </div>
    <div class="deal-card-destination">{dest_city}</div>
    {dest_country_html}
  </div>
  <div class="deal-card-body">
    <div class="deal-card-route">{route_display}</div>
    <div class="deal-card-iata">{route_iata}</div>
    <div class="deal-card-dates">📅 {date_label}</div>
    <div class="deal-card-price">{price_label}</div>
    <div class="deal-card-miles">🏆 {miles_label} <span class="miles-est-tag">estimadas*</span></div>
    <div class="deal-card-meta">
      Score: <strong>{score}/100</strong> &nbsp;·&nbsp; {airline}
    </div>
    {combined_note}
    {link_btn}
  </div>
</div>
""".strip()


def render_deal_card(deal: dict) -> None:
    """Render a single deal card in the current Streamlit column."""
    st.markdown(_build_card_html(deal), unsafe_allow_html=True)


def render_deal_cards_section(
    title: str,
    deals: list[dict],
    subtitle: str = "",
    per_row: int = 3,
    show_demo_note: bool = True,
) -> None:
    """Render a titled section with a grid of deal cards."""
    has_demo = any(d.get("is_demo") for d in deals)

    st.markdown(
        f'<div class="deals-section-header">{title}</div>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(
            f'<p class="deals-section-subtitle">{subtitle}</p>',
            unsafe_allow_html=True,
        )

    if not deals:
        st.info("Nenhuma oportunidade encontrada para esta categoria.")
        return

    for start in range(0, len(deals), per_row):
        chunk = deals[start: start + per_row]
        cols = st.columns(len(chunk))
        for col, deal in zip(cols, chunk):
            with col:
                render_deal_card(deal)

    if has_demo and show_demo_note:
        st.caption(
            "Dados marcados como **Modo Demo** são exemplos ilustrativos. "
            "Configure o token Travelpayouts na sidebar para ver passagens reais."
        )
    st.caption(
        "* Milhas estimadas com base em R$ 0,035/milha. "
        "Não representa disponibilidade real em programas de fidelidade."
    )
    st.write("")
