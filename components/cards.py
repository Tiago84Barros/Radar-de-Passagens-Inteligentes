from __future__ import annotations

import hashlib
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


def _card_id(deal: dict) -> str:
    """Generate a stable short ID for CSS scoping."""
    key = str(deal.get("id") or str(deal.get("origin_iata", "")) + str(deal.get("destination_iata", "")) + str(deal.get("departure_date", "")))
    return "dc" + hashlib.md5(key.encode()).hexdigest()[:8]


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
    booking_link = deal.get("booking_link") or "#"
    is_demo = bool(deal.get("is_demo"))
    via_hub = str(deal.get("via_hub") or "")
    is_combined = bool(via_hub)

    image_url = deal.get("image_url") or ""
    gradient = deal.get("gradient") or "linear-gradient(135deg,#0d3b2e,#07263a)"

    # Build background value
    if image_url:
        bg = (
            f"linear-gradient(180deg,rgba(8,17,31,.05) 0%,rgba(8,17,31,.75) 65%,"
            f"rgba(8,17,31,.95) 100%), url({image_url}), {gradient}"
        )
    else:
        bg = f"linear-gradient(180deg,rgba(8,17,31,.30) 0%,rgba(8,17,31,.92) 100%), {gradient}"

    # Scoped style block avoids Streamlit parser issues with long inline style attributes
    cid = _card_id(deal)
    scoped_css = (
        f"<style>"
        f"#{cid} .deal-card-header{{"
        f"background-image:{bg};"
        f"background-color:#0d1e30;"
        f"background-size:cover;"
        f"background-position:center;"
        f"}}"
        f"</style>"
    )

    demo_badge = "DEMO" if is_demo else ""
    connection_badge = f"via {via_hub}" if is_combined else ""

    if is_combined:
        route_display = f"{origin_iata} &rarr; {via_hub} &rarr; {dest_iata}"
        route_iata = f"{origin_city} &rarr; {via_hub} &rarr; {dest_city}"
        combined_note = (
            '<div class="deal-card-combined-note">'
            '&#9888;&#65039; Soma de dois trechos &mdash; reserve cada trecho individualmente.'
            '</div>'
        )
    else:
        route_display = f"{origin_city} &rarr; {dest_city}"
        route_iata = f"{origin_iata} &rarr; {dest_iata}"
        combined_note = ""

    if not is_demo and booking_link and booking_link != "#":
        link_btn = f'<a class="deal-card-btn" href="{booking_link}" target="_blank" rel="noopener">Ver detalhes &rarr;</a>'
    else:
        link_btn = '<a class="deal-card-btn deal-card-btn-demo" href="https://www.google.com/flights" target="_blank" rel="noopener">Buscar voo &rarr;</a>'

    dest_country_html = f'<div class="deal-card-country">{dest_country}</div>' if dest_country else ""

    # Badges as plain text inside span tags — no nested quotes in attribute values
    badges = f'<span class="deal-badge {cat_css}">{cat_label}</span>'
    badges += f'<span class="deal-badge {cls_css}">{cls_label}</span>'
    if connection_badge:
        badges += f'<span class="deal-badge badge-connection">{connection_badge}</span>'
    if demo_badge:
        badges += f'<span class="deal-badge badge-demo">{demo_badge}</span>'

    return (
        f'{scoped_css}'
        f'<div id="{cid}" class="deal-card">'
        f'<div class="deal-card-header">'
        f'<div class="deal-card-header-top">{badges}</div>'
        f'<div class="deal-card-destination">{dest_city}</div>'
        f'{dest_country_html}'
        f'</div>'
        f'<div class="deal-card-body">'
        f'<div class="deal-card-route">{route_display}</div>'
        f'<div class="deal-card-iata">{route_iata}</div>'
        f'<div class="deal-card-dates">&#128197; {date_label}</div>'
        f'<div class="deal-card-price">{price_label}</div>'
        f'<div class="deal-card-miles">&#127942; {miles_label} <span class="miles-est-tag">estimadas*</span></div>'
        f'<div class="deal-card-meta">Score: <strong>{score}/100</strong> &nbsp;&middot;&nbsp; {airline}</div>'
        f'{combined_note}'
        f'{link_btn}'
        f'</div>'
        f'</div>'
    )


# ─── airline comparison (per-airline cheapest) ──────────────────────────────

_AIRLINE_DIRECTORY: dict[str, str] = {
    "LA": "LATAM", "JJ": "LATAM", "G3": "GOL", "AD": "Azul", "TP": "TAP",
    "IB": "Iberia", "AF": "Air France", "AA": "American", "UA": "United",
    "AV": "Avianca", "CM": "Copa", "DL": "Delta", "KL": "KLM",
    "LH": "Lufthansa", "EK": "Emirates", "AR": "Aerolíneas",
}
_NAME_TO_CODE: dict[str, str] = {name.lower(): code for code, name in _AIRLINE_DIRECTORY.items()}
_NAME_TO_CODE.update({"latam": "LA", "gol": "G3", "azul": "AD"})


def _airline_visual(airline: str) -> tuple[str, str]:
    """Return (display_name, logo_html) for an airline name or IATA code."""
    raw = (airline or "").strip()
    if not raw or raw.lower() in {"não informada", "nao informada"}:
        return "Companhia não informada", '<span class="airline-logo-fallback">✈️</span>'
    if "+" in raw or "via" in raw.lower():
        return raw, '<span class="airline-logo-fallback">🔗</span>'

    up = raw.upper()
    code = None
    name = raw
    if up in _AIRLINE_DIRECTORY:
        code, name = up, _AIRLINE_DIRECTORY[up]
    else:
        low = raw.lower()
        for nm, cd in _NAME_TO_CODE.items():
            if nm in low:
                code, name = cd, _AIRLINE_DIRECTORY.get(cd, raw)
                break
    if code:
        logo = (
            f'<img class="airline-logo" src="https://pics.avs.io/120/40/{code}.png" '
            f'alt="{name}" loading="lazy" '
            f'onerror="this.style.display=&#39;none&#39;">'
        )
        return name, logo
    return raw, '<span class="airline-logo-fallback">✈️</span>'


def render_airline_comparison(deals: list[dict], route_label: str = "") -> None:
    """Render a per-airline price comparison, cheapest first, with logos."""
    if not deals:
        return

    title = "💺 Comparativo por companhia"
    if route_label:
        title += f" — {route_label}"
    st.markdown(f'<div class="deals-section-header">{title}</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="deals-section-subtitle">Menor preço encontrado em cada companhia. '
        'A mais barata aparece primeiro, marcada como <strong>melhor escolha</strong>.</p>',
        unsafe_allow_html=True,
    )

    cards: list[str] = []
    for i, deal in enumerate(deals):
        name, logo = _airline_visual(str(deal.get("airline") or ""))
        price = _fmt_brl(float(deal.get("price_brl") or 0))
        miles = format_miles(deal.get("estimated_miles") or 0)
        is_best = i == 0
        best_badge = '<span class="airline-best-badge">★ Melhor escolha</span>' if is_best else ""
        best_cls = " airline-cmp-card-best" if is_best else ""
        demo_tag = '<span class="airline-demo-tag">demo</span>' if deal.get("is_demo") else ""

        link = str(deal.get("booking_link") or "")
        if link and link != "#":
            btn = f'<a class="airline-cmp-btn" href="{link}" target="_blank" rel="noopener">Ver voo →</a>'
        else:
            btn = '<a class="airline-cmp-btn" href="https://www.google.com/flights" target="_blank" rel="noopener">Buscar →</a>'

        cards.append(
            f'<div class="airline-cmp-card{best_cls}">'
            f'<div class="airline-cmp-top">{logo}{best_badge}</div>'
            f'<div class="airline-cmp-name">{name}{demo_tag}</div>'
            f'<div class="airline-cmp-price">{price}</div>'
            f'<div class="airline-cmp-miles">🏆 {miles} <span class="miles-est-tag">est.*</span></div>'
            f'{btn}'
            f'</div>'
        )

    per_row = min(len(cards), 4)
    st.markdown(
        f'<div class="airline-cmp-grid" style="grid-template-columns:repeat({per_row},1fr);">'
        f'{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "* Milhas estimadas com base em R$ 0,035/milha. "
        "Não representa disponibilidade real em programas de fidelidade."
    )
    st.write("")


def render_deal_card(deal: dict) -> None:
    """Render a single deal card — wraps in a 1-column grid so CSS applies correctly."""
    st.markdown(
        f'<div class="deal-cards-grid" style="grid-template-columns:1fr;">{_build_card_html(deal)}</div>',
        unsafe_allow_html=True,
    )


def render_deal_cards_section(
    title: str,
    deals: list[dict],
    subtitle: str = "",
    per_row: int = 3,
    show_demo_note: bool = True,
) -> None:
    """Render a titled section with a grid of deal cards as a single HTML block."""
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

    # All cards rendered as one HTML block — avoids Streamlit column/markdown fragmentation
    cards_html = "".join(_build_card_html(deal) for deal in deals)
    st.markdown(
        f'<div class="deal-cards-grid" style="grid-template-columns:repeat({per_row},1fr);">'
        f'{cards_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if has_demo and show_demo_note:
        st.caption(
            "Dados marcados como **DEMO** são exemplos ilustrativos. "
            "Configure o token Travelpayouts na sidebar para ver passagens reais."
        )
    st.caption(
        "* Milhas estimadas com base em R$ 0,035/milha. "
        "Não representa disponibilidade real em programas de fidelidade."
    )
    st.write("")
