from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from app.formatting import format_brl
from app.location_resolver import LocationResolution, search_locations
from app.settings import get_settings
from app.styles import load_custom_css
from app.db import database_diagnostics, init_db
from data.airlines_catalog import get_airline_info, get_airline_name
from providers.provider_manager import search_all_providers, get_last_provider_diagnostic
from services import search_control_service
from services.miles_service import (
    DEFAULT_CENTS_PER_MILE,
    MILES_DISCLAIMER,
    compare_cash_vs_miles,
    estimate_miles_from_cash_price,
    format_miles,
)
from services.recommendation_service import rank_flight_options
from services.github_actions_service import is_configured as github_trigger_configured
from components.monitor_prompt import render_monitor_prompt
from utils.formatters import format_date_br, format_duration_short, format_stops

st.set_page_config(page_title="Radar de Passagens Inteligentes", page_icon="✈️", layout="wide")
load_custom_css()


def _airline_logos_html(airline_str: str | None, size: str = "normal") -> str:
    """Retorna HTML com os logos da(s) companhia(s) aérea(s).

    Aceita tanto IATA puro ("LA"), nome completo ("LATAM Airlines") quanto
    rotas combinadas ("LATAM Airlines + GOL Linhas Aéreas (via GRU)").
    Retorna string vazia quando não há logo disponível.
    size: "normal" (36px) | "small" (24px) usado nos cards de destaque.
    """
    import html as _html

    if not airline_str:
        return ""

    # Remove sufixo de hub "(via XYZ)" e divide em partes
    raw = airline_str.split("(via ")[0].strip()
    parts = [p.strip() for p in raw.split("+")]

    height = "36" if size == "normal" else "24"
    imgs = []
    for part in parts[:2]:          # no máximo 2 logos lado a lado
        info = get_airline_info(part.strip())
        if info.get("logo_url"):
            alt = _html.escape(info["name"])
            src = _html.escape(info["logo_url"])
            imgs.append(
                f'<img class="airline-logo airline-logo-{size}" '
                f'src="{src}" alt="{alt}" height="{height}" '
                f'onerror="this.style.display=\'none\'">'
            )

    if not imgs:
        return ""
    return f'<div class="airline-logos">{"".join(imgs)}</div>'

SORT_OPTIONS = {
    "Recomendados": "recomendados",
    "Menor preço": "menor_preco",
    "Menor duração": "menor_duracao",
    "Menos conexões": "menos_conexoes",
    "Melhor milhas": "melhor_milhas",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _location_option_label(loc: LocationResolution) -> str:
    if loc.location_type == "city":
        return f"🏙️ {loc.label} — todos os aeroportos da cidade"
    if loc.location_type == "country":
        return f"🌎 {loc.label} — aeroporto principal"
    return f"🛫 {loc.label}"


def _location_picker(label: str, state_key: str, placeholder: str) -> LocationResolution | None:
    query = st.text_input(label, value=st.session_state.get(state_key, ""), placeholder=placeholder, key=f"{state_key}_text")
    st.session_state[state_key] = query

    options = search_locations(query) if query.strip() else []
    if not options:
        if query.strip():
            st.caption("Nenhum aeroporto encontrado. Tente o nome da cidade ou o código IATA.")
        return None

    labels = [_location_option_label(opt) for opt in options]
    chosen_idx = st.selectbox(
        "Selecione",
        options=list(range(len(options))),
        format_func=lambda i: labels[i],
        key=f"{state_key}_choice",
        label_visibility="collapsed",
    )
    return options[chosen_idx]


def _offer_to_option(offer: dict, min_mile_value: float) -> dict:
    from services.miles_service import enrich_deal_with_miles

    deal = {
        "price_brl": float(offer.get("price") or 0),
        "airline": offer.get("airline") or "",
        "provider": offer.get("provider") or offer.get("source") or "",
        "source": offer.get("source") or offer.get("provider") or "",
        "source_name": offer.get("source_name") or "",
        "source_url": offer.get("source_url") or "",
        "stops": offer.get("stops"),
        "duration_minutes": offer.get("duration_minutes"),
        "departure_date": offer.get("departure_date"),
        "return_date": offer.get("return_date"),
        "booking_link": offer.get("booking_link") or "",
        "outbound_booking_link": offer.get("outbound_booking_link") or "",
        "return_booking_link": offer.get("return_booking_link") or "",
        "origin_iata": offer.get("origin") or "",
        "destination_iata": offer.get("destination") or "",
        "score": int(offer.get("score") or 0),
        "price_note": offer.get("price_note"),
        # Campos ricos vindos das buscas web (podem ser None nos demais providers)
        "price_outbound": offer.get("price_outbound"),
        "price_return": offer.get("price_return"),
        "connections": offer.get("connections") or [],
        "miles_offer": offer.get("miles_offer"),
        "category": offer.get("category"),
        "source_confidence": offer.get("source_confidence"),
        "separate_ticket": offer.get("separate_ticket"),
        "separate_round_trip": offer.get("separate_round_trip"),
        "airline_change": offer.get("airline_change"),
        "connection_risk": offer.get("connection_risk"),
    }
    return enrich_deal_with_miles(deal, min_mile_value)


def _run_manual_search(form: dict) -> dict[str, list[dict]]:
    """Busca os trechos separadamente: ida e (quando houver) volta, cada um
    como uma busca one-way própria — a tela mostra as opções de ida em cima e
    as de volta embaixo, cada bloco com sua ordenação."""
    min_mile_value = form.get("min_mile_value") or DEFAULT_CENTS_PER_MILE
    params = {
        "origin": form["origin_iata"],
        "destination": form["destination_iata"],
        "departure_date": form["departure_date"],
        "return_date": None,   # cada trecho e buscado como one-way
        "adults": form.get("adults", 1),
        "passengers": form.get("adults", 1),
        "currency": "BRL",
        "max_price": form.get("max_price"),
        "date_flex_days": form.get("date_flex_days", 0),
        "max_connection_hubs": form.get("max_connection_hubs", 4),
        "force_web_search": form.get("force_web_search", False),
    }
    outbound = search_all_providers(params)
    diag_outbound = get_last_provider_diagnostic()

    inbound: list[dict] = []
    diag_inbound: dict = {}
    packages: list[dict] = []
    diag_packages: dict = {}
    if form.get("return_date"):
        inbound = search_all_providers(
            {
                **params,
                "origin": form["destination_iata"],
                "destination": form["origin_iata"],
                "departure_date": form["return_date"],
            }
        )
        diag_inbound = get_last_provider_diagnostic()

        # Pacotes ida+volta: e o formato que as fontes mais publicam — uma
        # terceira consulta com as duas datas traz esses combos completos.
        packages = search_all_providers({**params, "return_date": form["return_date"]})
        diag_packages = get_last_provider_diagnostic()

    outbound_opts = [_offer_to_option(o, min_mile_value) for o in outbound]
    inbound_opts = [_offer_to_option(o, min_mile_value) for o in inbound]
    package_opts = [_offer_to_option(o, min_mile_value) for o in packages]

    # As fontes raramente devolvem o combo ida+volta fechado. Quando não vier
    # nenhum, montamos pacotes somando a ida + volta mais baratas (e combos por
    # companhia), para o bloco "Pacotes ida e volta" sempre mostrar um total.
    if form.get("return_date") and not package_opts:
        package_opts = _synthesize_packages(outbound_opts, inbound_opts, form, min_mile_value)

    return {
        "outbound": outbound_opts,
        "return": inbound_opts,
        "packages": package_opts,
        "diagnostics": {"ida": diag_outbound, "volta": diag_inbound, "pacotes": diag_packages},
    }


def _synthesize_packages(
    outbound_opts: list[dict], inbound_opts: list[dict], form: dict, min_mile_value: float
) -> list[dict]:
    """Monta pacotes ida+volta somando trechos quando as fontes não trazem o
    combo fechado: o overall mais barato (ida + volta) e, quando a mesma
    companhia aparece nos dois trechos, o combo dela. Preço = ida + volta."""
    from services.miles_service import enrich_deal_with_miles

    def _valid(opts: list[dict]) -> list[dict]:
        return sorted(
            [o for o in opts if float(o.get("price_brl") or 0) > 0],
            key=lambda o: float(o.get("price_brl") or 0),
        )

    out = _valid(outbound_opts)
    inn = _valid(inbound_opts)
    if not out or not inn:
        return []

    def _day(value) -> date | None:
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None

    requested_dep = _day(form.get("departure_date"))
    requested_ret = _day(form.get("return_date"))
    requested_duration = (
        (requested_ret - requested_dep).days
        if requested_dep and requested_ret and requested_ret > requested_dep
        else None
    )

    # Pares candidatos: o mais barato geral + o mais barato de cada companhia
    # presente nos dois trechos.
    pairs: list[tuple[dict, dict]] = [(out[0], inn[0])]
    cheapest_in_by_airline: dict[str, dict] = {}
    for o in inn:
        cheapest_in_by_airline.setdefault(str(o.get("airline") or "").strip().lower(), o)
    seen_out_airline: set[str] = set()
    for o in out:
        air = str(o.get("airline") or "").strip().lower()
        if not air or air in seen_out_airline:
            continue
        seen_out_airline.add(air)
        match = cheapest_in_by_airline.get(air)
        if match:
            pairs.append((o, match))

    packages: list[dict] = []
    seen_totals: set[tuple] = set()
    for ida, volta in pairs:
        actual_dep = _day(ida.get("departure_date"))
        actual_ret = _day(volta.get("departure_date"))
        if actual_dep is None or actual_ret is None or actual_ret <= actual_dep:
            continue
        if requested_duration is not None and (actual_ret - actual_dep).days != requested_duration:
            continue

        p_ida = float(ida.get("price_brl") or 0)
        p_volta = float(volta.get("price_brl") or 0)
        total = round(p_ida + p_volta, 2)
        same_airline = str(ida.get("airline") or "").strip().lower() == str(volta.get("airline") or "").strip().lower()
        airline = (ida.get("airline") or "") if same_airline else f"{ida.get('airline') or '?'} (ida) + {volta.get('airline') or '?'} (volta)"
        dedupe_key = (round(total, 2), airline)
        if dedupe_key in seen_totals:
            continue
        seen_totals.add(dedupe_key)
        dur_ida, dur_volta = ida.get("duration_minutes"), volta.get("duration_minutes")
        duration = (dur_ida + dur_volta) if (dur_ida and dur_volta) else None
        # Confiabilidade do pacote = a pior dos dois trechos.
        _confs = {str(ida.get("source_confidence") or ""), str(volta.get("source_confidence") or "")}
        pkg_conf = (
            "demo"
            if "demo" in _confs
            else ("unverified" if "unverified" in _confs else ("verified" if "verified" in _confs else "real"))
        )
        deal = {
            "price_brl": total,
            "price_outbound": p_ida,
            "price_return": p_volta,
            "airline": airline,
            "provider": "montado: ida + volta (2 bilhetes)",
            "source": "montado_ida_volta",
            "stops": (int(ida.get("stops") or 0) + int(volta.get("stops") or 0)),
            "duration_minutes": duration,
            "departure_date": actual_dep,
            "return_date": actual_ret,
            "booking_link": "",
            "outbound_booking_link": ida.get("booking_link") or "",
            "return_booking_link": volta.get("booking_link") or "",
            "origin_iata": form.get("origin_iata") or "",
            "destination_iata": form.get("destination_iata") or "",
            "price_note": None,  # é o total da viagem, não "somente ida"
            "connections": [],
            "miles_offer": None,
            "category": "pacote_montado",
            "source_confidence": pkg_conf,
            "separate_ticket": True,
            "separate_round_trip": True,
            "airline_change": not same_airline,
            "connection_risk": "baixo",
            "score": 0,
        }
        packages.append(enrich_deal_with_miles(deal, min_mile_value))

    packages.sort(key=lambda o: float(o.get("price_brl") or 0))
    return packages[:6]


# ── Result cards ──────────────────────────────────────────────────────────────

_HIGHLIGHT_VARIANT_CLASSES = {
    "recommended": "highlight-card-recommended",
    "cheapest": "highlight-card-cheapest",
    "fastest": "highlight-card-fastest",
}


def _summary_card(column, title: str, option: dict | None, badge: str, variant: str) -> None:
    """Renders one highlight (Recomendado / Mais barato / Mais rápido) as its
    own individual CSS card — instead of plain markdown text — so each stands
    out visually with its own accent color and shape."""
    import html as _html

    variant_class = _HIGHLIGHT_VARIANT_CLASSES.get(variant, "")
    badge_html = f"{badge} {_html.escape(title)}"

    with column:
        if not option:
            st.markdown(
                f"""
                <div class="highlight-card {variant_class}">
                    <div class="highlight-card-badge">{badge_html}</div>
                    <div class="highlight-card-empty">Sem opções para destacar.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

        price = _html.escape(format_brl(option["price_brl"]))
        airline_raw = option.get("airline") or ""
        meta = _html.escape(
            f"{get_airline_name(airline_raw)} · "
            f"{format_duration_short(option.get('duration_minutes')) or '—'} · "
            f"{format_stops(option.get('stops')) or '—'}"
        )
        miles = _html.escape(f"≈ {format_miles(option.get('estimated_miles') or 0)}")
        logo_html = _airline_logos_html(airline_raw, size="small")

        st.markdown(
            f"""
            <div class="highlight-card {variant_class}">
                <div class="highlight-card-badge">{badge_html}</div>
                {logo_html}
                <div class="highlight-card-price">{price}</div>
                <div class="highlight-card-meta">{meta}</div>
                <div class="highlight-card-miles">{miles}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


_CATEGORY_BADGES = {
    "mais_barata": "💰 Mais barata",
    "mais_rapida": "⚡ Mais rápida",
    "equilibrada": "⚖️ Melhor equilíbrio",
}


def _render_result_card(option: dict, min_mile_value: float) -> None:
    import html as _html

    price = option["price_brl"]

    airline_raw = option.get("airline") or ""
    airline = _html.escape(get_airline_name(airline_raw))
    logo_html = _airline_logos_html(airline_raw, size="normal")
    origin = _html.escape(option.get("origin_iata") or "—")
    dates = format_date_br(option.get("departure_date"))
    if option.get("return_date"):
        dates += f" → {format_date_br(option.get('return_date'))}"
    dates = _html.escape(dates)
    duration = _html.escape(format_duration_short(option.get("duration_minutes")) or "—")
    price_label = _html.escape(format_brl(price))
    provider = _html.escape(
        option.get("source_name") or option.get("source") or option.get("provider") or "—"
    )
    link = option.get("booking_link") or ""

    # ── Categoria (mais barata / mais rápida / equilibrada) ──────────────────
    badge = _CATEGORY_BADGES.get(str(option.get("category") or "").strip().lower())
    badge_html = f'<div class="result-card-category">{_html.escape(badge)}</div>' if badge else ""

    # ── Conexões com tempo de espera ─────────────────────────────────────────
    connections = option.get("connections") or []
    if connections:
        from data.destinations_catalog import AIRPORT_NAMES

        partes = []
        for c in connections:
            code = str(c.get("airport") or "?").upper()
            apt = _html.escape(AIRPORT_NAMES.get(code, code))
            espera = format_duration_short(c.get("wait_minutes")) if c.get("wait_minutes") else None
            partes.append(f"{apt} ({espera} de espera)" if espera else apt)
        stops_html = "&#128257; Conexão: " + " &rarr; ".join(partes)
    else:
        n_stops = option.get("stops")
        stops_html = (
            "&#9992;&#65039; Voo direto"
            if (n_stops is not None and int(n_stops or 0) == 0)
            else "&#128257; " + _html.escape(format_stops(n_stops) or "—")
        )

    # ── Preço ida / volta separados ──────────────────────────────────────────
    # Quando a fonte informa so um dos trechos, o outro e derivado do total
    # (total = ida + volta) para a volta sempre aparecer no card.
    p_ida, p_volta = option.get("price_outbound"), option.get("price_return")
    is_round_trip = bool(option.get("return_date"))
    price_note = option.get("price_note") or ""
    if is_round_trip and price_note != "preco_somente_ida":
        if p_ida and not p_volta and price > p_ida:
            p_volta = price - p_ida
        elif p_volta and not p_ida and price > p_volta:
            p_ida = price - p_volta
    rt_total = is_round_trip and price_note != "preco_somente_ida"
    rt_note_html = (
        '<div class="result-card-muted">💼 Valor total da viagem: ida + volta</div>' if rt_total else ""
    )
    if p_ida and p_volta:
        breakdown_html = (
            f'<div class="result-card-muted">Ida {_html.escape(format_brl(p_ida))} · '
            f'Volta {_html.escape(format_brl(p_volta))}</div>'
        )
    elif p_ida:
        breakdown_html = f'<div class="result-card-muted">Ida {_html.escape(format_brl(p_ida))}</div>'
    else:
        breakdown_html = ""
    breakdown_html = rt_note_html + breakdown_html

    # ── Milhas: preço real do programa quando o Gemini achou; senão estimativa ─
    rt_miles_note = ", ida + volta" if rt_total else ""
    miles_offer = option.get("miles_offer")
    if miles_offer and miles_offer.get("amount"):
        taxas = float(miles_offer.get("taxes_brl") or 0)
        taxas_txt = f" + {format_brl(taxas)} de taxas" if taxas else ""
        rt_suffix = " — ida + volta" if rt_total else ""
        miles_label = _html.escape(
            f"{format_miles(miles_offer['amount'])} no {miles_offer.get('program') or 'programa da companhia'}{taxas_txt}{rt_suffix}"
        )
    else:
        miles = option.get("estimated_miles") or estimate_miles_from_cash_price(price, min_mile_value)
        cmp = compare_cash_vs_miles(price, miles, option.get("taxes") or 0.0, min_mile_value)
        miles_label = _html.escape(
            f"≈ {format_miles(miles)} (estimativa{rt_miles_note}) · {cmp['recommendation']}"
        )

    outbound_link = option.get("outbound_booking_link") or ""
    return_link = option.get("return_booking_link") or ""
    if option.get("separate_round_trip") and (outbound_link or return_link):
        actions = []
        if outbound_link:
            actions.append(
                f'<a class="result-card-cta" href="{_html.escape(outbound_link, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">Comprar ida</a>'
            )
        if return_link:
            actions.append(
                f'<a class="result-card-cta" href="{_html.escape(return_link, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">Comprar volta</a>'
            )
        action_html = "".join(actions)
    elif link:
        action_label = (
            "Ver fonte confirmada"
            if str(option.get("source_confidence") or "").lower() == "verified"
            else "Comprar na companhia"
        )
        action_html = (
            f'<a class="result-card-cta" href="{_html.escape(link, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{action_label}</a>'
        )
    else:
        action_html = '<span class="result-card-cta result-card-cta-disabled">Sem link direto</span>'

    price_note_html = (
        '<div class="result-card-price-note">⚠️ Preço estimado só para a ida (conexão via hub)</div>'
        if price_note == "preco_somente_ida"
        else ""
    )

    # Selo de confiabilidade da fonte do preço.
    confidence = str(option.get("source_confidence") or "").lower()
    if confidence == "verified":
        price_note_html += (
            '<div class="result-card-price-note">✅ Tarifa vinculada à página citada '
            'pela busca web. Confira a disponibilidade ao abrir a fonte.</div>'
        )
    elif confidence == "unverified":
        price_note_html += (
            '<div class="result-card-price-note">⚠️ Preço informado por IA (busca web) — '
            'NÃO validado. Confirme no site da companhia antes de comprar.</div>'
        )
    elif confidence == "demo":
        price_note_html += (
            '<div class="result-card-price-note">⚠️ Valor ilustrativo (demonstração) — não é preço real.</div>'
        )

    # Avisos diferentes para ida/volta em reservas independentes e para
    # self-transfer no meio de um itinerário.
    if option.get("separate_ticket"):
        if option.get("separate_round_trip"):
            price_note_html += (
                '<div class="result-card-price-note">⚠️ Ida e volta em duas reservas separadas. '
                'Alterações, cancelamentos e bagagem são tratados independentemente.</div>'
            )
        else:
            _troca = " com troca de companhia" if option.get("airline_change") else ""
            price_note_html += (
                f'<div class="result-card-price-note">⚠️ 2 bilhetes separados{_troca} (sem proteção de '
                'conexão). Deixe 6h+ entre os voos — se o 1º atrasar, o 2º é perdido.</div>'
            )

    # st.html() bypasses Streamlit's Markdown parser entirely — avoids the bug
    # where 4+ spaces of indentation or special chars in URLs (& = ? `) cause the
    # HTML block to be treated as a Markdown code block and displayed as raw text.
    st.html(
        f'<div class="result-card">'
        f'{badge_html}'
        f'<div class="result-card-col result-card-airline">'
        f'{logo_html}'
        f'<div class="result-card-airline-name">{airline}</div>'
        f'<div class="result-card-muted">{origin}</div>'
        f'</div>'
        f'<div class="result-card-col result-card-route">'
        f'<div class="result-card-dates">{dates}</div>'
        f'<div class="result-card-muted">&#9203; {duration}</div>'
        f'<div class="result-card-muted">{stops_html}</div>'
        f'</div>'
        f'<div class="result-card-col result-card-price">'
        f'<div class="result-card-price-value">{price_label}</div>'
        f'{breakdown_html}'
        f'<div class="result-card-muted">&#11088; {miles_label}</div>'
        f'{price_note_html}'
        f'</div>'
        f'<div class="result-card-col result-card-action">'
        f'{action_html}'
        f'<div class="result-card-source">Fonte: {provider}</div>'
        f'</div>'
        f'</div>'
    )


# Ordenações disponíveis em cada bloco de trecho (ida / volta)
_LEG_SORT_OPTIONS = {
    "💰 Menor preço": "menor_preco",
    "⚡ Menor duração": "menor_duracao",
}


def _leg_budget(total_max_price) -> float | None:
    """Teto de UM trecho (ida ou volta) = metade do orçamento total da viagem.
    None quando não há limite (0/None)."""
    try:
        total = float(total_max_price or 0)
    except (TypeError, ValueError):
        return None
    return (total / 2.0) if total > 0 else None


def _render_leg_section(
    title: str, subtitle: str, options: list[dict], *, key: str, form: dict, diag: dict | None = None
) -> None:
    """Bloco de resultados (ida, volta ou pacote): título, ordenação própria e cards."""
    st.markdown(f"### {title}")
    st.caption(subtitle)

    # Poucos resultados: mostra o que cada fonte respondeu para este trecho,
    # para diagnóstico ficar visível sem precisar abrir logs.
    if diag and len(options) <= 2:
        bits = [str(diag.get("message") or "")]
        if diag.get("openai"):
            bits.append(f"OpenAI: {diag['openai']}")
        if diag.get("travelpayouts_apoio"):
            bits.append(f"Travelpayouts: {diag['travelpayouts_apoio']}")
        if diag.get("travelpayouts_erro"):
            bits.append(f"Travelpayouts: {diag['travelpayouts_erro']}")
        joined = " · ".join(b for b in bits if b)
        if joined:
            st.caption(f"🔎 Fontes deste trecho: {joined}")

    if not options:
        st.info("Nenhuma tarifa encontrada para este trecho. Tente datas mais flexíveis ou remova filtros.")
        return
    sort_label = st.radio(
        "Ordenar por",
        list(_LEG_SORT_OPTIONS.keys()),
        horizontal=True,
        key=f"leg_sort_{key}",
    )
    prefs = dict(form, sort_by=_LEG_SORT_OPTIONS[sort_label])
    # max_price é o orçamento TOTAL da viagem (ida + volta), dividido igualmente:
    # cada trecho (ida ou volta) é limitado à METADE desse total.
    if key in ("ida", "volta"):
        prefs["max_price"] = _leg_budget(form.get("max_price"))
    ranking = rank_flight_options(options, prefs)
    for option in ranking["sorted_options"]:
        _render_result_card(option, form.get("min_mile_value") or DEFAULT_CENTS_PER_MILE)


# ── Tabs ──────────────────────────────────────────────────────────────────────

def _render_search_tab() -> None:
    with st.sidebar:
        st.markdown("## ✈️ Buscar passagem")
        origin_res = _location_picker("Origem", "search_origin_input", "Ex.: GRU ou São Paulo")
        destination_res = _location_picker("Destino", "search_destination_input", "Ex.: LIS ou Lisboa")
        col_a, col_b = st.columns(2)
        departure_date = col_a.date_input("Ida", value=date.today() + timedelta(days=30), format="DD/MM/YYYY")
        trip_type = st.radio("Tipo de viagem", ["Ida e volta", "Somente ida"], horizontal=True)
        return_date = None
        if trip_type == "Ida e volta":
            return_date = col_b.date_input("Volta", value=departure_date + timedelta(days=7), format="DD/MM/YYYY")
        adults = st.number_input("Passageiros", min_value=1, max_value=9, value=1)

        st.markdown("---")
        st.markdown("**Preferências**")
        max_price = st.number_input(
            "Preço máximo da viagem (R$)",
            min_value=0.0,
            value=0.0,
            step=50.0,
            help=(
                "Quanto você aceita pagar pela viagem inteira (ida + volta). O app divide "
                "igualmente entre os trechos: cada lado é limitado à metade desse total. "
                "Ex.: R$ 4.000 → ida até R$ 2.000 e volta até R$ 2.000. "
                "Em viagem só de ida, é a tarifa única. 0 = sem limite."
            ),
        )
        consider_miles = st.checkbox("Considerar opções em milhas", value=True)
        min_mile_value = st.number_input(
            "Valor mínimo aceitável por milha (R$)", min_value=0.001, value=DEFAULT_CENTS_PER_MILE, step=0.001, format="%.3f"
        )
        max_stops = st.selectbox("Máximo de conexões", ["Sem limite", "Direto", "Até 1", "Até 2"], index=0)
        max_stops_value = {"Sem limite": None, "Direto": 0, "Até 1": 1, "Até 2": 2}[max_stops]
        max_duration_hours = st.slider(
            "Duração máxima da viagem (horas)",
            min_value=2,
            max_value=40,
            value=40,
            step=1,
            help="Arraste até o máximo para não aplicar limite de duração.",
        )
        max_duration_minutes_value = None if max_duration_hours >= 40 else max_duration_hours * 60

        with st.expander("🔧 Fontes e alcance da busca"):
            st.caption(
                "Ajuste até onde o radar vai para achar tarifas — buscas mais "
                "amplas demoram um pouco mais, mas aumentam a chance de achar "
                "um preço melhor."
            )
            _FLEX_OPTIONS = ["0", "2", "5", "7", "10", "15 (mês inteiro)"]
            _FLEX_VALUES   = { "0": 0, "2": 2, "5": 5, "7": 7, "10": 10, "15 (mês inteiro)": 15 }
            flex_label = st.select_slider(
                "Tolerância de datas (dias para cada lado)",
                options=_FLEX_OPTIONS,
                value="0",
                help=(
                    "Além da data escolhida, busca tarifas nos dias vizinhos. "
                    "Ex.: '5' = de -5 a +5 dias em torno da data de ida. "
                    "'Mês inteiro' (±15 dias) cobre praticamente todo o mês, "
                    "aumentando muito a chance de achar uma tarifa publicada."
                ),
            )
            date_flex_days = _FLEX_VALUES[flex_label]
            if date_flex_days == 15:
                st.caption("🗓️ Buscando em qualquer dia do mês — pode demorar um pouco mais.")
            max_connection_hubs = st.slider(
                "Aeroportos de conexão a tentar",
                min_value=0,
                max_value=6,
                value=4,
                step=1,
                help=(
                    "Quantos aeroportos brasileiros (GRU, GIG, BSB, CGH...) o "
                    "radar tenta como conexão para montar rotas combinadas mais "
                    "baratas que o voo direto — mesmo que isso signifique trocar "
                    "de avião no meio do caminho. 0 desativa essa busca."
                ),
            )
            force_web_search = st.checkbox(
                "Sempre cruzar com pesquisa web (IA)",
                value=False,
                help=(
                    "Por padrão, a pesquisa via IA (Gemini + Google Search) só "
                    "entra como apoio quando a Travelpayouts não retorna nada. "
                    "Ative para sempre cruzar os preços com uma pesquisa web "
                    "extra e aumentar o alcance das fontes — a busca fica mais "
                    "lenta, mas cobre mais lugares."
                ),
            )

        search_clicked = st.button("🔍 Buscar passagens", type="primary", use_container_width=True)

    if search_clicked:
        if not origin_res or not destination_res:
            st.error("Não foi possível identificar a origem e/ou o destino. Use o código IATA (ex.: GRU) ou o nome da cidade.")
            return
        form = {
            "origin_iata": origin_res.code,
            "origin_city": origin_res.label,
            "destination_iata": destination_res.code,
            "destination_city": destination_res.label,
            "departure_date": departure_date,
            "return_date": return_date,
            "adults": int(adults),
            "trip_type": "round_trip" if trip_type == "Ida e volta" else "one_way",
            "max_price": max_price or None,
            "consider_miles": consider_miles,
            "min_mile_value": float(min_mile_value),
            "max_stops": max_stops_value,
            "max_duration_minutes": max_duration_minutes_value,
            "search_window_days": int(date_flex_days),
            "telegram_enabled": True,
            "date_flex_days": int(date_flex_days),
            "max_connection_hubs": int(max_connection_hubs),
            "force_web_search": bool(force_web_search),
        }
        st.session_state["last_search_form"] = form
        with st.spinner("Buscando as melhores tarifas..."):
            try:
                st.session_state["last_search_results"] = _run_manual_search(form)
                st.session_state["last_search_error"] = None
            except Exception as exc:  # noqa: BLE001
                st.session_state["last_search_results"] = []
                st.session_state["last_search_error"] = str(exc)

    form = st.session_state.get("last_search_form")
    results_data = st.session_state.get("last_search_results") or {}
    if isinstance(results_data, list):
        # Sessão antiga (formato de lista única) — trata tudo como ida.
        results_data = {"outbound": results_data, "return": []}
    outbound: list[dict] = results_data.get("outbound") or []
    inbound: list[dict] = results_data.get("return") or []
    results = outbound + inbound + (results_data.get("packages") or [])
    error = st.session_state.get("last_search_error")

    if not form:
        st.title("Encontre a melhor passagem para sua próxima viagem")
        st.subheader("Compare tarifas reais e descubra a recomendação certa para você.")
        st.info("Informe origem, destino e datas para encontrar as melhores tarifas.")
        return

    st.markdown(f"### {form['origin_iata']} → {form['destination_iata']}")
    st.caption(
        f"{format_date_br(form['departure_date'])}"
        + (f" – {format_date_br(form['return_date'])}" if form.get("return_date") else "")
        + f" · {form['adults']} passageiro(s)"
    )

    if error:
        _err = str(error)
        if "token" in _err.lower() or "401" in _err or "403" in _err:
            st.error("Travelpayouts não configurado ou token inválido. Verifique o secret TRAVELPAYOUTS_API_TOKEN nas configurações do app.")
        else:
            st.error(f"Não foi possível consultar a API de passagens agora. Tente novamente em alguns instantes. ({_err[:200]})")
        return
    if not results:
        diag = get_last_provider_diagnostic()
        st.warning(
            "Nenhuma tarifa encontrada para esta combinação. "
            "Tente datas mais flexíveis, outro aeroporto ou remova filtros."
        )
        if diag.get("provider") == "gemini_web_search" and diag.get("status") == "not_configured":
            st.info(
                "💡 A busca via IA (Gemini) está desativada neste app — ela ajuda "
                "justamente em rotas de nicho como esta, onde a Travelpayouts "
                "ainda não tem cache de preços. Configure o secret "
                "`GEMINI_API_KEY` para ativar essa fonte adicional."
            )
        _gem_msg = str(diag.get("message") or "")
        if "RESOURCE_EXHAUSTED" in _gem_msg or "429" in _gem_msg:
            if "prepayment" in _gem_msg or "credits are depleted" in _gem_msg:
                st.error(
                    "🚫 A busca via Gemini falhou: os créditos pré-pagos do projeto "
                    "Google AI Studio desta chave estão esgotados. Recarregue os "
                    "créditos ou troque a `GEMINI_API_KEY` por uma chave de um "
                    "projeto no nível gratuito em https://aistudio.google.com/apikey."
                )
            else:
                st.error(
                    "🚫 A busca via Gemini falhou: limite de uso da API atingido "
                    "(429). Aguarde a renovação da cota ou verifique o billing do "
                    "projeto em https://ai.studio/projects."
                )
        elif diag.get("status") == "real_empty" and _gem_msg.startswith("erro Gemini"):
            st.error(f"🚫 A busca via Gemini falhou: {_gem_msg}")
        _oai_msg = str(diag.get("openai") or "")
        if _oai_msg.startswith("erro OpenAI"):
            st.error(f"🚫 A busca via OpenAI falhou: {_oai_msg}")
        coverage_note = diag.get("coverage_note")
        if coverage_note:
            st.caption(f"🔎 Diagnóstico: {coverage_note}")
        return

    if form.get("return_date"):
        # Ida e volta: trechos buscados separadamente — opções de ida em cima,
        # opções de volta embaixo, cada bloco com sua própria ordenação.
        diagnostics = results_data.get("diagnostics") or {}
        # Teto de cada trecho = metade do orçamento total — exibido no subtítulo
        # para o usuário ver as três informações: total, ida (½) e volta (½).
        _leg_cap = _leg_budget(form.get("max_price"))
        _cap_note = f" · 💰 Teto deste trecho: {format_brl(_leg_cap)} (½ do orçamento)" if _leg_cap else ""
        _render_leg_section(
            "🛫 Voos de ida",
            f"{form['origin_iata']} → {form['destination_iata']} · {format_date_br(form['departure_date'])}{_cap_note}",
            outbound,
            key="ida",
            form=form,
            diag=diagnostics.get("ida"),
        )
        st.markdown("---")
        _render_leg_section(
            "🛬 Voos de volta",
            f"{form['destination_iata']} → {form['origin_iata']} · {format_date_br(form['return_date'])}{_cap_note}",
            inbound,
            key="volta",
            form=form,
            diag=diagnostics.get("volta"),
        )
        st.markdown("---")
        _packages = results_data.get("packages") or []
        _synthesized = any(p.get("source") == "montado_ida_volta" for p in _packages)
        _pkg_subtitle = (
            f"{form['origin_iata']} → {form['destination_iata']} → {form['origin_iata']} · "
            f"{format_date_br(form['departure_date'])} → {format_date_br(form['return_date'])} · "
            "Preço e milhas valem pela viagem completa (ida + volta)."
        )
        if _synthesized:
            _pkg_subtitle += (
                " · 🧩 Montado a partir da ida + volta mais baratas (2 bilhetes separados — "
                "as fontes não trouxeram o pacote fechado)."
            )
        _render_leg_section(
            "📦 Pacotes ida e volta",
            _pkg_subtitle,
            _packages,
            key="pacotes",
            form=form,
            diag=diagnostics.get("pacotes"),
        )
    else:
        sort_label = st.selectbox("Ordenar por", list(SORT_OPTIONS.keys()), index=0)
        prefs = dict(form, sort_by=SORT_OPTIONS[sort_label])
        ranking = rank_flight_options(outbound, prefs)

        cols = st.columns(3)
        _summary_card(cols[0], "Recomendado", ranking["recommended_option"], "🏆", "recommended")
        _summary_card(cols[1], "Mais barato", ranking["cheapest_option"], "💰", "cheapest")
        _summary_card(cols[2], "Mais rápido", ranking["fastest_option"], "⚡", "fastest")
        st.caption(f"💡 {ranking['reason']}")

        st.markdown("---")
        for option in ranking["sorted_options"]:
            _render_result_card(option, form.get("min_mile_value") or DEFAULT_CENTS_PER_MILE)

    st.markdown("---")
    render_monitor_prompt(form)
    st.caption(MILES_DISCLAIMER)


def _render_monitored_tab() -> None:
    st.title("📡 Buscas monitoradas")
    st.caption("O radar acompanha estas rotas até a data da viagem e avisa no Telegram quando encontra a melhor tarifa.")

    monitors = search_control_service.list_monitored()
    if not monitors:
        st.info("Nenhuma busca está sendo monitorada agora. Ative o rastreamento após uma busca na aba Buscar.")
        return

    for m in monitors:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 3, 2])
            with c1:
                st.markdown(f"**{m['origin_iata']} → {m['destination_iata']}**")
                st.caption(
                    f"{format_date_br(m['departure_date'])}"
                    + (f" – {format_date_br(m['return_date'])}" if m.get("return_date") else "")
                )
                st.caption(f"Status: {m['status']}")
            with c2:
                st.caption(f"Última verificação: {format_date_br(m.get('last_checked_at')) or '—'}")
                if m.get("last_best_price"):
                    st.markdown(f"Última melhor passagem: **{format_brl(m['last_best_price'])}**")
                if m.get("last_status_message"):
                    st.caption(m["last_status_message"])
                if m.get("last_best_link"):
                    st.link_button("Ver oferta", m["last_best_link"])
            with c3:
                if m["status"] == "active":
                    if st.button("⏸️ Pausar", key=f"pause_{m['id']}", use_container_width=True):
                        search_control_service.pause_search(m["id"])
                        st.rerun()
                else:
                    if st.button("▶️ Reativar", key=f"resume_{m['id']}", use_container_width=True):
                        search_control_service.resume_search(m["id"])
                        st.rerun()
                if st.button("🚀 Executar agora", key=f"run_{m['id']}", use_container_width=True):
                    with st.spinner("Executando..."):
                        result = search_control_service.run_now(m["id"])
                    st.toast(result.get("message") or "Executado.")
                    st.rerun()
                if st.button("🗑️ Excluir", key=f"del_{m['id']}", use_container_width=True):
                    search_control_service.delete_search(m["id"])
                    st.rerun()


def _render_miles_tab() -> None:
    st.title("🏆 Milhas")
    st.caption(MILES_DISCLAIMER)

    col1, col2 = st.columns(2)
    with col1:
        price = st.number_input("Preço em dinheiro (R$)", min_value=0.0, value=1500.0, step=50.0)
        miles_required = st.number_input("Milhas necessárias", min_value=0.0, value=25000.0, step=500.0)
        taxes = st.number_input("Taxas de emissão (R$)", min_value=0.0, value=150.0, step=10.0)
        min_mile_value = st.number_input(
            "Seu valor mínimo aceitável por milha (R$)", min_value=0.001, value=DEFAULT_CENTS_PER_MILE, step=0.001, format="%.3f"
        )
    with col2:
        cmp = compare_cash_vs_miles(price, miles_required, taxes, min_mile_value)
        st.metric("Valor implícito por milha", f"R$ {cmp['mile_value']:.3f}".replace(".", ","))
        st.markdown(f"### {cmp['recommendation']}")
        st.write(cmp["reason"])
        st.markdown(f"Estimativa de milhas para {format_brl(price)}: **{format_miles(estimate_miles_from_cash_price(price, min_mile_value))}**")


def _render_settings_tab() -> None:
    st.title("⚙️ Configurações")
    st.caption("Status das integrações configuradas (nunca exibimos segredos aqui).")

    settings = get_settings()
    diag = database_diagnostics()
    rows = [
        ("Gemini (busca web de tarifas)", bool(getattr(settings, "gemini_api_key", None))),
        ("OpenAI / ChatGPT (busca web de tarifas)", bool(getattr(settings, "openai_api_key", None))),
        ("Travelpayouts (fonte primária de preços)", bool(getattr(settings, "travelpayouts_api_token", None))),
        ("Telegram", bool(settings.telegram_bot_token and settings.telegram_chat_id)),
        ("Banco de dados", diag["driver"] != "-"),
        ("GitHub Actions (executar agora)", github_trigger_configured()),
    ]
    for label, ok in rows:
        st.markdown(f"{'✅' if ok else '⚠️'} **{label}** — {'configurado' if ok else 'não configurado'}")

    st.markdown("---")
    st.info(
        "🛰️ O app só exibe tarifas publicadas pela Travelpayouts ou vinculadas "
        "às citações nativas das buscas web do Gemini/OpenAI. Sem fonte, não há resultado."
    )
    st.caption(f"Banco: {diag['driver']} · host {diag['host']} · fonte: {diag['source']}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    init_db()
    tabs = st.tabs(["Buscar", "Buscas Monitoradas", "Milhas", "Configurações"])
    with tabs[0]:
        _render_search_tab()
    with tabs[1]:
        _render_monitored_tab()
    with tabs[2]:
        _render_miles_tab()
    with tabs[3]:
        _render_settings_tab()


if __name__ == "__main__":
    main()
