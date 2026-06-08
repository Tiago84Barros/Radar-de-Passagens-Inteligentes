from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from app.formatting import format_brl
from app.location_resolver import LocationResolution, search_locations
from app.settings import get_settings
from app.styles import load_custom_css
from app.db import database_diagnostics, init_db
from data.airlines_catalog import get_airline_name
from providers.provider_manager import search_all_providers
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
        "stops": offer.get("stops"),
        "duration_minutes": offer.get("duration_minutes"),
        "departure_date": offer.get("departure_date"),
        "return_date": offer.get("return_date"),
        "booking_link": offer.get("booking_link") or "",
        "origin_iata": offer.get("origin") or "",
        "destination_iata": offer.get("destination") or "",
        "score": int(offer.get("score") or 0),
    }
    return enrich_deal_with_miles(deal, min_mile_value)


def _run_manual_search(form: dict) -> list[dict]:
    params = {
        "origin": form["origin_iata"],
        "destination": form["destination_iata"],
        "departure_date": form["departure_date"],
        "return_date": form.get("return_date"),
        "adults": form.get("adults", 1),
        "passengers": form.get("adults", 1),
        "currency": "BRL",
        "max_price": form.get("max_price"),
        "date_flex_days": form.get("date_flex_days", 0),
        "max_connection_hubs": form.get("max_connection_hubs", 4),
        "force_web_search": form.get("force_web_search", False),
    }
    offers = search_all_providers(params)
    return [_offer_to_option(o, form.get("min_mile_value") or DEFAULT_CENTS_PER_MILE) for o in offers]


# ── Result cards ──────────────────────────────────────────────────────────────

def _summary_card(column, title: str, option: dict | None, badge: str) -> None:
    with column:
        st.markdown(f"#### {badge} {title}")
        if not option:
            st.caption("Sem opções para destacar.")
            return
        st.markdown(f"**{format_brl(option['price_brl'])}**")
        st.caption(
            f"{get_airline_name(option.get('airline') or '')} · "
            f"{format_duration_short(option.get('duration_minutes')) or '—'} · "
            f"{format_stops(option.get('stops')) or '—'}"
        )
        st.caption(f"≈ {format_miles(option.get('estimated_miles') or 0)}")


def _render_result_card(option: dict, min_mile_value: float) -> None:
    import html as _html

    price = option["price_brl"]
    miles = option.get("estimated_miles") or estimate_miles_from_cash_price(price, min_mile_value)
    cmp = compare_cash_vs_miles(price, miles, option.get("taxes") or 0.0, min_mile_value)

    airline = _html.escape(get_airline_name(option.get("airline") or ""))
    origin = _html.escape(option.get("origin_iata") or "—")
    dates = _html.escape(
        f"{format_date_br(option.get('departure_date'))} → {format_date_br(option.get('return_date'))}"
    )
    duration = _html.escape(format_duration_short(option.get("duration_minutes")) or "—")
    stops = _html.escape(format_stops(option.get("stops")) or "—")
    price_label = _html.escape(format_brl(price))
    miles_label = _html.escape(f"≈ {format_miles(miles)} · {cmp['recommendation']}")
    provider = _html.escape(option.get("provider") or "—")
    link = option.get("booking_link") or ""

    if link:
        action_html = f'<a class="result-card-cta" href="{_html.escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">Veja mais</a>'
    else:
        action_html = '<span class="result-card-cta result-card-cta-disabled">Veja mais</span>'

    st.markdown(
        f"""
        <div class="result-card">
            <div class="result-card-col result-card-airline">
                <div class="result-card-airline-name">{airline}</div>
                <div class="result-card-muted">{origin}</div>
            </div>
            <div class="result-card-col result-card-route">
                <div class="result-card-dates">{dates}</div>
                <div class="result-card-muted">⏱ {duration} · 🔁 {stops}</div>
            </div>
            <div class="result-card-col result-card-price">
                <div class="result-card-price-value">{price_label}</div>
                <div class="result-card-muted">{miles_label}</div>
            </div>
            <div class="result-card-col result-card-action">
                {action_html}
                <div class="result-card-source">Fonte: {provider}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
        max_price = st.number_input("Preço máximo (R$)", min_value=0.0, value=0.0, step=50.0, help="0 = sem limite")
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
            date_flex_days = st.slider(
                "Tolerância de datas (dias para cada lado)",
                min_value=0,
                max_value=5,
                value=0,
                step=1,
                help=(
                    "Além da data escolhida, também busca tarifas reais nos dias "
                    "vizinhos (ex.: 2 = de -2 a +2 dias). Preço de passagem varia "
                    "bastante de um dia para o outro — alargar a janela aumenta a "
                    "chance de achar algo bem mais barato perto da data desejada."
                ),
            )
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
            "search_window_days": 1,
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
    results: list[dict] = st.session_state.get("last_search_results") or []
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
        st.error(f"Não foi possível concluir a busca: {error}")
        return
    if not results:
        st.warning("Nenhuma tarifa encontrada para esta busca. Tente outras datas ou destino.")
        return

    sort_label = st.selectbox("Ordenar por", list(SORT_OPTIONS.keys()), index=0)
    prefs = dict(form, sort_by=SORT_OPTIONS[sort_label])
    ranking = rank_flight_options(results, prefs)

    cols = st.columns(3)
    _summary_card(cols[0], "Recomendado", ranking["recommended_option"], "🏆")
    _summary_card(cols[1], "Mais barato", ranking["cheapest_option"], "💰")
    _summary_card(cols[2], "Mais rápido", ranking["fastest_option"], "⚡")
    st.caption(f"💡 {ranking['reason']}")

    st.markdown("---")
    for option in ranking["sorted_options"]:
        _render_result_card(option, form.get("min_mile_value") or DEFAULT_CENTS_PER_MILE)

    st.markdown("---")
    render_monitor_prompt(form)
    st.caption(MILES_DISCLAIMER)


def _render_monitored_tab() -> None:
    st.title("📡 Buscas monitoradas")
    st.caption("O radar acompanha estas rotas por 24h e avisa no Telegram quando encontra a melhor tarifa.")

    monitors = search_control_service.list_monitored()
    if not monitors:
        st.info("Nenhuma busca está sendo monitorada agora. Ative o rastreamento de 24h após uma busca na aba Buscar.")
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
        ("Travelpayouts (fonte de preços)", bool(settings.travelpayouts_api_token)),
        ("Gemini (apoio/fallback)", bool(settings.gemini_api_key)),
        ("Telegram", bool(settings.telegram_bot_token and settings.telegram_chat_id)),
        ("Banco de dados", diag["driver"] != "-"),
        ("GitHub Actions (executar agora)", github_trigger_configured()),
    ]
    for label, ok in rows:
        st.markdown(f"{'✅' if ok else '⚠️'} **{label}** — {'configurado' if ok else 'não configurado'}")

    st.markdown("---")
    st.info("🛰️ Scraping desativado. O app usa somente APIs configuradas (Travelpayouts + Gemini).")
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
