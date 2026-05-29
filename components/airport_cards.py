from __future__ import annotations

import streamlit as st

from data.destinations_catalog import get_destination_info


def _airport_card_html(info: dict, badge_label: str, badge_kind: str) -> str:
    """Build the HTML for a single origin/destination postcard card."""
    iata = str(info.get("iata") or "").upper()
    city = info.get("city") or iata
    airport = info.get("airport_name") or ""
    country = info.get("country") or ""
    image_url = info.get("image_url") or ""
    gradient = info.get("gradient") or "linear-gradient(135deg,#0d3b2e,#07263a)"

    if image_url:
        bg = (
            f"linear-gradient(180deg,rgba(8,17,31,.12) 0%,rgba(8,17,31,.72) 60%,"
            f"rgba(8,17,31,.95) 100%), url({image_url}), {gradient}"
        )
    else:
        bg = f"linear-gradient(180deg,rgba(8,17,31,.35) 0%,rgba(8,17,31,.92) 100%), {gradient}"

    cid = f"apc-{badge_kind}-{iata}"
    airport_html = f'<div class="airport-card-name">🛬 {airport}</div>' if airport else ""
    country_html = f'<div class="airport-card-country">{country}</div>' if country else ""

    return (
        f"<style>#{cid}{{background-image:{bg};}}</style>"
        f'<div id="{cid}" class="airport-card">'
        f'<div class="airport-card-overlay">'
        f'<span class="airport-card-badge badge-{badge_kind}">{badge_label}</span>'
        f'<div class="airport-card-code">{iata}</div>'
        f'<div class="airport-card-city">{city}</div>'
        f'{country_html}'
        f'{airport_html}'
        f'</div>'
        f'</div>'
    )


def render_airport_cards(origin_code: str, destination_code: str | None = None) -> None:
    """Render the origin card (and destination card alongside, if provided).

    Side by side on desktop, stacked on mobile (st.columns handles the reflow).
    """
    origin_code = (origin_code or "").upper().strip()
    if not origin_code:
        return
    origin_info = get_destination_info(origin_code)

    dest_code = (destination_code or "").upper().strip()
    if dest_code:
        col_o, col_d = st.columns(2)
        with col_o:
            st.markdown(
                _airport_card_html(origin_info, "🛫 Origem", "origin"),
                unsafe_allow_html=True,
            )
        with col_d:
            dest_info = get_destination_info(dest_code)
            st.markdown(
                _airport_card_html(dest_info, "🛬 Destino", "dest"),
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            _airport_card_html(origin_info, "🛫 Origem", "origin"),
            unsafe_allow_html=True,
        )
