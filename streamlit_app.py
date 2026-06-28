from __future__ import annotations

import html as _html
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
from services.official_search_links import build_official_search_links
from services.recommendation_service import rank_flight_options
from services.serpapi_account_service import fetch_serpapi_usage
from services.choice_assistant_service import (
    ENGINE_AUTO,
    ENGINE_GEMINI,
    ENGINE_LOCAL,
    ENGINE_OPENAI,
    analyze_confirmed_offers,
    assistant_engines,
)
from services.github_actions_service import is_configured as github_trigger_configured
from components.monitor_prompt import render_monitor_prompt
from utils.formatters import format_date_br, format_duration_short, format_stops

st.set_page_config(page_title="Radar de Passagens Inteligentes", page_icon="✈️", layout="wide")
load_custom_css()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_serpapi_usage() -> dict[str, Any]:
    return fetch_serpapi_usage()


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

MAX_LEG_CANDIDATES = 20
MAX_ROUND_TRIP_CANDIDATES = 40
MAX_DISPLAYED_ROUND_TRIPS = 15


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
        "max_stops": form.get("max_stops"),
        "max_duration_minutes": form.get("max_duration_minutes"),
        "date_flex_days": form.get("date_flex_days", 0),
        "max_connection_hubs": form.get("max_connection_hubs", 4),
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
                "min_departure_date": form["departure_date"],
            }
        )
        diag_inbound = get_last_provider_diagnostic()

        # Pacotes ida+volta: e o formato que as fontes mais publicam — uma
        # terceira consulta com as duas datas traz esses combos completos.
        packages = search_all_providers({**params, "return_date": form["return_date"]})
        diag_packages = get_last_provider_diagnostic()

    outbound_opts = [_offer_to_option(o, min_mile_value) for o in outbound]
    inbound_opts = _filter_return_options(
        [_offer_to_option(o, min_mile_value) for o in inbound],
        form.get("departure_date"),
    )
    package_opts = [_offer_to_option(o, min_mile_value) for o in packages]

    comparison_packages = list(package_opts)
    if form.get("return_date"):
        # Compara sempre os pacotes fechados das APIs com compras separadas.
        # Isso não faz novas chamadas: apenas cruza as tarifas de ida e volta
        # que já foram confirmadas acima.
        separate_packages = _synthesize_packages(
            outbound_opts,
            inbound_opts,
            form,
            min_mile_value,
        )
        comparison_packages = _merge_round_trip_candidates(
            package_opts,
            separate_packages,
            form,
        )
        package_opts = comparison_packages[:MAX_DISPLAYED_ROUND_TRIPS]

    return {
        "outbound": outbound_opts,
        "return": inbound_opts,
        "packages": package_opts,
        "comparison_packages": comparison_packages,
        "diagnostics": {"ida": diag_outbound, "volta": diag_inbound, "pacotes": diag_packages},
    }


def _filter_return_options(options: list[dict], outbound_date: Any) -> list[dict]:
    outbound_day = _parse_ui_day(outbound_date)
    if outbound_day is None:
        return options
    return [
        option
        for option in options
        if (return_day := _parse_ui_day(option.get("departure_date"))) is not None
        and return_day > outbound_day
    ]


def _parse_ui_day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _synthesize_packages(
    outbound_opts: list[dict], inbound_opts: list[dict], form: dict, min_mile_value: float
) -> list[dict]:
    """Build viable confirmed round trips from independent outbound/inbound legs."""
    from services.miles_service import enrich_deal_with_miles

    def _valid(opts: list[dict]) -> list[dict]:
        valid = [o for o in opts if float(o.get("price_brl") or 0) > 0]
        if not valid:
            return []
        ranking = rank_flight_options(valid, {**form, "sort_by": "recomendados"})
        selected: list[dict] = []
        prioritized = [
            ranking.get("cheapest_option"),
            ranking.get("fastest_option"),
            *ranking["sorted_options"],
        ]
        for option in prioritized:
            if option is not None and option not in selected:
                selected.append(option)
            if len(selected) >= MAX_LEG_CANDIDATES:
                break
        return selected

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

    packages: list[dict] = []
    seen_combinations: set[tuple] = set()
    for ida in out:
        for volta in inn:
            actual_dep = _day(ida.get("departure_date"))
            actual_ret = _day(volta.get("departure_date"))
            if actual_dep is None or actual_ret is None or actual_ret <= actual_dep:
                continue
            if requested_duration is not None and (actual_ret - actual_dep).days != requested_duration:
                continue

            p_ida = float(ida.get("price_brl") or 0)
            p_volta = float(volta.get("price_brl") or 0)
            total = round(p_ida + p_volta, 2)
            ida_airline = str(ida.get("airline") or "").strip()
            volta_airline = str(volta.get("airline") or "").strip()
            same_airline = ida_airline.lower() == volta_airline.lower()
            airline = (
                ida_airline
                if same_airline
                else f"{ida_airline or '?'} (ida) + {volta_airline or '?'} (volta)"
            )
            dedupe_key = (
                actual_dep,
                actual_ret,
                round(total, 2),
                ida_airline.lower(),
                volta_airline.lower(),
                ida.get("booking_link") or "",
                volta.get("booking_link") or "",
            )
            if dedupe_key in seen_combinations:
                continue
            seen_combinations.add(dedupe_key)

            dur_ida = int(ida.get("duration_minutes") or 0)
            dur_volta = int(volta.get("duration_minutes") or 0)
            duration = dur_ida + dur_volta if dur_ida and dur_volta else None
            ida_stops = int(ida.get("stops") or 0)
            volta_stops = int(volta.get("stops") or 0)

            # Confiabilidade do conjunto = a pior confiabilidade dos dois trechos.
            confidences = {
                str(ida.get("source_confidence") or ""),
                str(volta.get("source_confidence") or ""),
            }
            package_confidence = (
                "demo"
                if "demo" in confidences
                else (
                    "unverified"
                    if "unverified" in confidences
                    else ("verified" if "verified" in confidences else "real")
                )
            )
            deal = {
                "price_brl": total,
                "price_outbound": p_ida,
                "price_return": p_volta,
                "airline": airline,
                "outbound_airline": ida_airline,
                "return_airline": volta_airline,
                "provider": "montado: ida + volta (2 bilhetes)",
                "source": "montado_ida_volta",
                "source_name": "Ida + volta em reservas separadas",
                "stops": ida_stops + volta_stops,
                "outbound_stops": ida_stops,
                "return_stops": volta_stops,
                "duration_minutes": duration,
                "outbound_duration_minutes": dur_ida or None,
                "return_duration_minutes": dur_volta or None,
                "departure_date": actual_dep,
                "return_date": actual_ret,
                "booking_link": "",
                "outbound_booking_link": ida.get("booking_link") or "",
                "return_booking_link": volta.get("booking_link") or "",
                "origin_iata": form.get("origin_iata") or "",
                "destination_iata": form.get("destination_iata") or "",
                "price_note": None,
                "connections": [],
                "miles_offer": None,
                "category": "pacote_montado",
                "source_confidence": package_confidence,
                "separate_ticket": True,
                "separate_round_trip": True,
                "airline_change": not same_airline,
                "connection_risk": "baixo",
                "score": 0,
            }
            packages.append(enrich_deal_with_miles(deal, min_mile_value))

    if not packages:
        return []
    ranking = rank_flight_options(packages, {**form, "sort_by": "recomendados"})
    return list(ranking["sorted_options"])[:MAX_ROUND_TRIP_CANDIDATES]


def _merge_round_trip_candidates(
    api_packages: list[dict],
    separate_packages: list[dict],
    form: dict,
) -> list[dict]:
    """Merge API packages and separate reservations into one ranked universe."""
    unique: dict[tuple, dict] = {}
    for option in [*api_packages, *separate_packages]:
        key = (
            str(option.get("departure_date") or "")[:10],
            str(option.get("return_date") or "")[:10],
            round(float(option.get("price_brl") or 0), 2),
            str(option.get("airline") or "").strip().lower(),
            bool(option.get("separate_round_trip")),
            str(option.get("booking_link") or ""),
            str(option.get("outbound_booking_link") or ""),
            str(option.get("return_booking_link") or ""),
        )
        unique.setdefault(key, option)

    candidates = list(unique.values())
    if not candidates:
        return []
    ranking = rank_flight_options(candidates, {**form, "sort_by": "recomendados"})
    selected = list(ranking["sorted_options"])[:MAX_ROUND_TRIP_CANDIDATES]
    for group in (
        [option for option in candidates if not option.get("separate_round_trip")],
        [option for option in candidates if option.get("separate_round_trip")],
    ):
        if not group:
            continue
        group_ranking = rank_flight_options(group, {**form, "sort_by": "recomendados"})
        representative = group_ranking.get("recommended_option")
        if representative is None or representative in selected:
            continue
        if len(selected) >= MAX_ROUND_TRIP_CANDIDATES:
            selected[-1] = representative
        else:
            selected.append(representative)
    return selected


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

    # Milhas reais só entram quando um provider estruturado informar esse dado;
    # caso contrario, o app exibe estimativa claramente identificada.
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
            '<div class="result-card-price-note">✅ Tarifa vinculada a uma fonte verificada. '
            'Confira a disponibilidade ao abrir a fonte.</div>'
        )
    elif confidence == "unverified":
        price_note_html += (
            '<div class="result-card-price-note">⚠️ Fonte não validada automaticamente. '
            'Confirme no site da companhia antes de comprar.</div>'
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
        if diag.get("serpapi"):
            bits.append(f"SerpApi: {diag['serpapi']}")
        if diag.get("travelpayouts"):
            bits.append(f"Travelpayouts: {diag['travelpayouts']}")
        if diag.get("serpapi_erro"):
            bits.append(f"SerpApi: {diag['serpapi_erro']}")
        if diag.get("travelpayouts_erro"):
            bits.append(f"Travelpayouts: {diag['travelpayouts_erro']}")
        joined = " · ".join(b for b in bits if b)
        if joined:
            st.caption(f"🔎 Fontes deste trecho: {joined}")

    if not options:
        st.info("Nenhuma tarifa encontrada para este trecho. Tente datas mais flexíveis ou remova filtros.")
        if key in ("ida", "volta"):
            _render_official_search_shortcuts(form)
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


def _render_official_search_shortcuts(form: dict) -> None:
    links = build_official_search_links(form)
    if not links:
        return
    st.markdown("#### Consultar nas fontes")
    st.caption(
        "As APIs configuradas nao confirmaram preco. Estes botoes abrem a busca "
        "nas fontes reais, sem registrar valores como tarifa encontrada."
    )
    cols = st.columns(min(len(links), 4))
    for index, link in enumerate(links):
        with cols[index % len(cols)]:
            st.link_button(link["label"], link["url"], use_container_width=True)


def _render_choice_assistant(options: list[dict], form: dict) -> None:
    """Render a grounded recommendation whose facts always come from APIs."""
    if not options:
        return

    st.markdown("---")
    st.markdown("### Assistente de Escolha")
    st.caption(
        "Compara somente as tarifas confirmadas acima. A IA pode escolher entre "
        "essas opções, mas preços, datas e links continuam vindo das APIs."
    )

    settings = get_settings()
    available = assistant_engines(settings)
    labels = {
        ENGINE_AUTO: "Automático",
        ENGINE_LOCAL: "Análise local",
        ENGINE_OPENAI: "OpenAI",
        ENGINE_GEMINI: "Gemini",
    }
    choices = [ENGINE_LOCAL]
    if len(available) > 1:
        choices = [ENGINE_AUTO, *[engine for engine in available if engine != ENGINE_LOCAL], ENGINE_LOCAL]
    selected_engine = st.radio(
        "Motor da análise",
        choices,
        format_func=lambda value: labels[value],
        horizontal=True,
        key="choice_assistant_engine",
    )

    if st.button("Analisar custo-benefício", key="choice_assistant_run", type="primary"):
        with st.spinner("Comparando as opções confirmadas..."):
            st.session_state["choice_assistant_result"] = analyze_confirmed_offers(
                options,
                form,
                engine=selected_engine,
                settings=settings,
            )

    result = st.session_state.get("choice_assistant_result")
    if not result:
        return
    if not result.get("ok"):
        st.info(result.get("message") or "Não há opções confirmadas para analisar.")
        return

    if form.get("return_date"):
        st.markdown("#### Comparação dos formatos de compra")
        comparison_cols = st.columns(2)
        comparison_items = [
            ("Reserva única", result.get("best_closed_offer")),
            ("Ida e volta separadas", result.get("best_separate_offer")),
        ]
        for column, (label, option) in zip(comparison_cols, comparison_items):
            with column:
                st.markdown(f"**{label}**")
                if option:
                    st.markdown(f"**{format_brl(option['price_brl'])}**")
                    st.caption(
                        f"{format_duration_short(option.get('duration_minutes')) or 'duração não informada'} · "
                        f"{format_stops(option.get('stops')) or 'conexões não informadas'}"
                    )
                else:
                    st.caption("Nenhuma opção confirmada neste formato.")

    selected = result["selected_offer"]
    airline = get_airline_name(selected.get("airline") or "") or "opção confirmada"
    verdict_label = {
        "single_booking": "Reserva única mais vantajosa",
        "separate_reservations": "Trechos separados mais vantajosos",
        "one_way": "Melhor opção de ida",
    }.get(result.get("verdict_kind"), "Melhor custo-benefício")
    st.markdown(f"#### Veredito: {verdict_label}")
    st.markdown(f"**{airline}**")
    st.markdown(
        f"**{format_brl(selected['price_brl'])}** · "
        f"{format_duration_short(selected.get('duration_minutes')) or 'duração não informada'} · "
        f"{format_stops(selected.get('stops')) or 'conexões não informadas'}"
    )
    if result.get("verdict_kind") == "separate_reservations":
        outbound_airline = get_airline_name(selected.get("outbound_airline") or "") or "companhia não informada"
        return_airline = get_airline_name(selected.get("return_airline") or "") or "companhia não informada"
        st.markdown(
            f"Ida: **{outbound_airline}**, {format_brl(selected.get('price_outbound') or 0)} · "
            f"{format_duration_short(selected.get('outbound_duration_minutes')) or 'duração não informada'}"
        )
        st.markdown(
            f"Volta: **{return_airline}**, {format_brl(selected.get('price_return') or 0)} · "
            f"{format_duration_short(selected.get('return_duration_minutes')) or 'duração não informada'}"
        )
    st.caption(
        f"Análise: {result['engine_label']} · "
        f"{result['confirmed_count']} tarifa(s) confirmada(s) comparada(s)"
    )
    for reason in result.get("reasons") or []:
        st.markdown(f"- {reason}")
    for warning in result.get("warnings") or []:
        st.warning(warning)

    if result.get("fallback_reason"):
        st.info(result["fallback_reason"])

    alternative = result.get("alternative_offer")
    if alternative:
        alternative_airline = (
            get_airline_name(alternative.get("airline") or "") or "outra opção"
        )
        st.caption(
            f"Alternativa mais econômica: {alternative_airline} por "
            f"{format_brl(alternative['price_brl'])}."
        )

    booking_link = selected.get("booking_link") or selected.get("source_url")
    outbound_link = selected.get("outbound_booking_link")
    return_link = selected.get("return_booking_link")
    if booking_link:
        st.link_button("Abrir fonte confirmada", booking_link)
    elif outbound_link or return_link:
        cols = st.columns(2)
        if outbound_link:
            cols[0].link_button("Abrir fonte da ida", outbound_link, use_container_width=True)
        if return_link:
            cols[1].link_button("Abrir fonte da volta", return_link, use_container_width=True)


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
        search_clicked = st.button("🔍 Buscar passagens", type="primary", use_container_width=True)

    if search_clicked:
        if not origin_res or not destination_res:
            st.error("Não foi possível identificar a origem e/ou o destino. Use o código IATA (ex.: GRU) ou o nome da cidade.")
            return
        if return_date and return_date <= departure_date:
            st.error("A data de volta precisa ser depois da data de ida.")
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
        }
        st.session_state["last_search_form"] = form
        st.session_state.pop("choice_assistant_result", None)
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
            st.error("API de passagens não configurada ou chave inválida. Verifique os secrets SERPAPI_API_KEY e TRAVELPAYOUTS_API_TOKEN.")
        else:
            st.error(f"Não foi possível consultar a API de passagens agora. Tente novamente em alguns instantes. ({_err[:200]})")
        return
    if not results:
        diag = get_last_provider_diagnostic()
        st.warning(
            "Nenhuma tarifa foi confirmada automaticamente para esta combinação. "
            "Isso pode acontecer quando as APIs configuradas não têm cobertura, "
            "cache ou disponibilidade para a rota/data."
        )
        if diag.get("serpapi_erro"):
            st.error(f"🚫 SerpApi: {diag['serpapi_erro']}")
        if diag.get("travelpayouts_erro"):
            st.error(f"🚫 Travelpayouts: {diag['travelpayouts_erro']}")
        coverage_note = diag.get("coverage_note")
        if coverage_note:
            st.caption(f"🔎 Diagnóstico: {coverage_note}")
        _render_official_search_shortcuts(form)
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
                " · 🧩 Inclui combinações de ida + volta em 2 reservas separadas, "
                "comparadas com os pacotes fechados das APIs."
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

    if form.get("return_date"):
        assistant_options = (
            results_data.get("comparison_packages")
            or results_data.get("packages")
            or []
        )
    else:
        assistant_options = outbound
    _render_choice_assistant(assistant_options, form)

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


def _format_usage_count(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _integration_status_html(rows: list[tuple[str, bool]]) -> str:
    items = []
    for label, configured in rows:
        state_class = "is-ok" if configured else "is-off"
        state_label = "Configurado" if configured else "Não configurado"
        items.append(
            f'<div class="settings-status-item {state_class}">'
            f'<span class="settings-status-dot" aria-hidden="true"></span>'
            f'<div class="settings-status-copy">'
            f'<div class="settings-status-name">{_html.escape(label)}</div>'
            f'<div class="settings-status-state">{state_label}</div>'
            f'</div>'
            f'</div>'
        )
    return f'<div class="settings-status-grid">{"".join(items)}</div>'


def _serpapi_usage_html(usage: dict[str, Any]) -> str:
    if not usage.get("ok"):
        message = _html.escape(
            str(usage.get("message") or "Limite da SerpApi indisponível.")
        )
        return (
            '<section class="serpapi-quota-panel level-error">'
            '<div class="serpapi-quota-head">'
            '<div><div class="serpapi-quota-kicker">Controle de consumo</div>'
            '<div class="serpapi-quota-title">Uso da SerpApi</div></div>'
            '</div>'
            f'<div class="serpapi-quota-error">{message}</div>'
            '</section>'
        )

    level = str(usage.get("level") or "normal").lower()
    if level not in {"normal", "warning", "critical", "exhausted"}:
        level = "normal"
    level_label = {
        "normal": "Cota saudável",
        "warning": "Atenção ao saldo",
        "critical": "Saldo crítico",
        "exhausted": "Cota esgotada",
    }[level]
    plan_name = _html.escape(str(usage.get("plan_name") or "Plano SerpApi"))
    used_percent = min(max(float(usage.get("used_percent") or 0), 0.0), 100.0)
    remaining_percent = usage.get("remaining_percent")
    remaining_label = (
        f"{float(remaining_percent):.1f}% restante"
        if remaining_percent is not None
        else "Saldo percentual indisponível"
    )

    metrics = [
        ("Usadas neste mês", _format_usage_count(usage.get("monthly_usage"))),
        ("Saldo disponível", _format_usage_count(usage.get("total_searches_left"))),
        ("Limite mensal", _format_usage_count(usage.get("monthly_limit"))),
        (
            "Uso na última hora",
            f"{_format_usage_count(usage.get('last_hour_searches'))} / "
            f"{_format_usage_count(usage.get('hourly_limit'))}",
        ),
    ]
    metric_html = "".join(
        f'<div class="serpapi-quota-stat">'
        f'<div class="serpapi-quota-label">{_html.escape(label)}</div>'
        f'<div class="serpapi-quota-value">{_html.escape(value)}</div>'
        f'</div>'
        for label, value in metrics
    )

    alert_html = ""
    if level == "warning":
        alert_html = (
            '<div class="serpapi-quota-alert warning">'
            f"Restam {float(remaining_percent or 0):.1f}% da cota mensal."
            "</div>"
        )
    elif level == "critical":
        alert_html = (
            '<div class="serpapi-quota-alert critical">'
            f"Restam apenas {float(remaining_percent or 0):.1f}% da cota mensal."
            "</div>"
        )
    elif level == "exhausted":
        alert_html = (
            '<div class="serpapi-quota-alert exhausted">'
            "Cota esgotada. As buscas dependerão da Travelpayouts."
            "</div>"
        )

    extra_credits = int(usage.get("extra_credits") or 0)
    extra_note = (
        f" · {_format_usage_count(extra_credits)} crédito(s) extra(s)"
        if extra_credits > 0
        else ""
    )
    return (
        f'<section class="serpapi-quota-panel level-{level}">'
        '<div class="serpapi-quota-head">'
        '<div><div class="serpapi-quota-kicker">Controle de consumo</div>'
        '<div class="serpapi-quota-title">Uso da SerpApi</div></div>'
        f'<div class="serpapi-plan-badge">{plan_name} · {level_label}</div>'
        '</div>'
        f'<div class="serpapi-quota-grid">{metric_html}</div>'
        '<div class="serpapi-progress-row">'
        f'<span><strong>{used_percent:.1f}%</strong> utilizado</span>'
        f'<span>{_html.escape(remaining_label)}</span>'
        '</div>'
        '<div class="serpapi-progress-track" role="progressbar" '
        f'aria-valuenow="{used_percent:.1f}" aria-valuemin="0" aria-valuemax="100">'
        f'<div class="serpapi-progress-fill" style="width:{used_percent:.1f}%"></div>'
        '</div>'
        f'{alert_html}'
        f'<div class="serpapi-quota-foot">Atualização em cache por até 5 minutos{extra_note}</div>'
        '</section>'
    )


def _render_serpapi_usage() -> None:
    usage = _cached_serpapi_usage()
    st.html(_serpapi_usage_html(usage))


def _render_settings_tab() -> None:
    st.title("⚙️ Configurações")
    st.caption("Status das integrações configuradas (nunca exibimos segredos aqui).")

    settings = get_settings()
    diag = database_diagnostics()
    rows = [
        ("SerpApi Google Flights (API principal de preços)", bool(getattr(settings, "serpapi_api_key", None))),
        ("Travelpayouts (API complementar/cache)", bool(getattr(settings, "travelpayouts_api_token", None))),
        ("OpenAI (consultoria sobre tarifas confirmadas)", bool(settings.openai_api_key)),
        ("Gemini (consultoria sobre tarifas confirmadas)", bool(settings.gemini_api_key)),
        ("Telegram", bool(settings.telegram_bot_token and settings.telegram_chat_id)),
        ("Banco de dados", diag["driver"] != "-"),
        ("GitHub Actions (executar agora)", github_trigger_configured()),
    ]
    st.markdown("### Integrações")
    st.html(_integration_status_html(rows))

    _render_serpapi_usage()
    st.markdown("---")
    st.info(
        "🛰️ O app só exibe tarifas retornadas por APIs configuradas "
        "(SerpApi Google Flights e/ou Travelpayouts). "
        "Gemini e OpenAI apenas comparam opções já confirmadas; elas não pesquisam nem criam preços. "
        "Sem fonte confirmada, não há resultado."
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
