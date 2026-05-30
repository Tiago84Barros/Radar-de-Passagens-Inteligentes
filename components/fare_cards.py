from __future__ import annotations

import streamlit as st

from components.cards import _airline_visual, _classification_info
from utils.formatters import (
    format_brl,
    format_collected_age,
    format_date_br,
    format_duration_short,
    format_miles,
    format_stops,
    quote_age_hours,
)

_TIP_MILES = (
    "Milhas estimadas (preço ÷ R$ 0,035). A disponibilidade real depende do "
    "programa de fidelidade."
)

# Quotes collected more than this many hours ago get a discreet "stale" warning
# on the card — airfares expire fast, so old snapshots may no longer exist.
_STALE_AFTER_HOURS = 24


def _freshness_html(deal: dict) -> str:
    """Build the 'collected ago' chip (and stale warning) for a fare card."""
    age_label = format_collected_age(deal.get("collected_at"))
    if not age_label:
        return ""
    hours = quote_age_hours(deal.get("collected_at"))
    is_stale = hours is not None and hours >= _STALE_AFTER_HOURS
    cls = "fare-card-age fare-card-age-stale" if is_stale else "fare-card-age"
    icon = "⏳" if is_stale else "🕓"
    chip = f'<div class="{cls}">{icon} Coletado {age_label}</div>'
    if is_stale:
        chip += (
            '<div class="fare-card-note">⚠️ Preço coletado há mais de 24h — '
            'pode ter mudado ou expirado. Confirme no site antes de comprar.</div>'
        )
    return chip


def _route_html(deal: dict) -> str:
    o_city = deal.get("origin_city") or deal.get("origin_iata") or "–"
    d_city = deal.get("destination_city") or deal.get("destination_iata") or "–"
    o_iata = deal.get("origin_iata") or ""
    d_iata = deal.get("destination_iata") or ""
    via_hub = str(deal.get("via_hub") or "").strip()
    if via_hub:
        return (
            f'<div class="fare-card-route">{o_city} &rarr; {via_hub} &rarr; {d_city}</div>'
            f'<div class="fare-card-route-iata">{o_iata} &rarr; {via_hub} &rarr; {d_iata}</div>'
        )
    return (
        f'<div class="fare-card-route">{o_city} &rarr; {d_city}</div>'
        f'<div class="fare-card-route-iata">{o_iata} &rarr; {d_iata}</div>'
    )


def _fare_card_html(deal: dict, is_cheapest: bool) -> str:
    name, logo = _airline_visual(str(deal.get("airline") or ""))
    price = float(deal.get("price_brl") or 0)
    miles = deal.get("estimated_miles") or 0
    score = int(deal.get("score") or 0)
    classification = str(deal.get("classification") or "")
    cls_css, cls_label = _classification_info(classification, score)

    dep = format_date_br(deal.get("departure_date"))
    ret = format_date_br(deal.get("return_date"))
    dur = format_duration_short(deal.get("duration_minutes"))
    stops = format_stops(deal.get("stops"))
    provider = str(deal.get("provider") or "—")
    via_hub = str(deal.get("via_hub") or "").strip()

    best_badge = (
        '<div class="fare-card-best">🏷️ Menor preço encontrado</div>' if is_cheapest else ""
    )
    best_cls = " fare-card-cheapest" if is_cheapest else ""

    meta_bits = []
    if dur:
        meta_bits.append(f"⏱ {dur}")
    if stops:
        meta_bits.append(stops)
    meta_line = " · ".join(meta_bits) if meta_bits else "tempo não informado"

    combined_note = (
        '<div class="fare-card-note">⚠️ Soma de dois trechos — reserve cada trecho '
        'separadamente.</div>'
        if via_hub else ""
    )

    link = str(deal.get("booking_link") or "")
    if link and link not in {"#", ""}:
        btn = f'<a class="fare-card-btn" href="{link}" target="_blank" rel="noopener">Ver / comprar →</a>'
    else:
        btn = '<a class="fare-card-btn" href="https://www.google.com/flights" target="_blank" rel="noopener">Buscar voo →</a>'

    return (
        f'<div class="fare-card{best_cls}">'
        f'{best_badge}'
        f'<div class="fare-card-head">{logo}<span class="fare-card-airline">{name}</span>'
        f'<span class="fare-badge {cls_css}">{cls_label}</span></div>'
        f'{_route_html(deal)}'
        f'<div class="fare-card-dates">📅 Ida {dep} &nbsp;·&nbsp; Volta {ret}</div>'
        f'<div class="fare-card-price">{format_brl(price)}</div>'
        f'<div class="fare-card-miles" title="{_TIP_MILES}">🏆 {format_miles(miles)} '
        f'<span class="miles-est-tag">estimadas*</span></div>'
        f'<div class="fare-card-meta">{meta_line}</div>'
        f'<div class="fare-card-foot">Score {score}/100 · {provider}</div>'
        f'{_freshness_html(deal)}'
        f'{combined_note}'
        f'{btn}'
        f'</div>'
    )


def render_fare_cards(deals: list[dict], per_row: int = 3) -> None:
    """Render the "Melhores tarifas encontradas" section: one card per airline,
    cheapest first and highlighted. ``deals`` should already be sorted by price."""
    st.markdown(
        '<div class="deals-section-header">💸 Melhores tarifas encontradas</div>',
        unsafe_allow_html=True,
    )
    if not deals:
        st.markdown(
            '<div class="dados-ausentes">📭 <strong>Sem tarifas ainda</strong><br>'
            '<span>Clique em <strong>Buscar agora</strong> na lateral para consultar os preços '
            'desta rota.</span></div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<p class="deals-section-subtitle">Menor preço encontrado em cada companhia. '
        'O cartão mais barato aparece destacado.</p>',
        unsafe_allow_html=True,
    )

    cheapest_price = min(float(d.get("price_brl") or 0) for d in deals if (d.get("price_brl") or 0) > 0)
    cards = []
    for deal in deals:
        is_cheapest = float(deal.get("price_brl") or 0) == cheapest_price
        cards.append(_fare_card_html(deal, is_cheapest))

    per_row = max(1, min(per_row, len(cards)))
    st.markdown(
        f'<div class="fare-cards-grid" style="grid-template-columns:repeat({per_row},1fr);">'
        f'{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "* Milhas estimadas (R$ 0,035/milha). A disponibilidade real depende do "
        "programa de fidelidade."
    )
