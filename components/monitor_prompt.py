from __future__ import annotations

import streamlit as st

from app.db import session_scope
from services.database_service import (
    create_monitored_search,
    find_existing_monitor,
    replace_monitored_search,
)
from utils.formatters import format_date_br


def _route_key(config: dict) -> str:
    o = str(config.get("origin_iata") or "").upper()
    d = str(config.get("destination_iata") or "").upper()
    dep = config.get("departure_date")
    return f"{o}->{d}@{dep}"


def _render_replace_dialog(config: dict, existing_summary: dict) -> None:
    o, d = existing_summary["origin_iata"], existing_summary["destination_iata"]
    when = format_date_br(existing_summary.get("departure_date"))
    st.markdown(
        f'<div class="monitor-conflict">⚠️ Já existe uma busca monitorada: '
        f'<strong>{o} → {d}</strong> em <strong>{when}</strong>. Deseja substituir?</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    if c1.button("Manter atual", key="monitor_keep", use_container_width=True):
        st.session_state.pop("monitor_conflict", None)
        st.session_state["monitor_feedback"] = {"level": "info", "text": f"Mantida a busca monitorada {o} → {d}."}
        st.rerun()
    if c2.button("Substituir", key="monitor_replace", type="primary", use_container_width=True):
        with session_scope() as db:
            existing = find_existing_monitor(db, o, d)
            if existing:
                replace_monitored_search(db, existing, config)
            else:
                create_monitored_search(db, config)
        st.session_state.pop("monitor_conflict", None)
        new_o = str(config.get("origin_iata") or "").upper()
        new_d = str(config.get("destination_iata") or "").upper()
        st.session_state["monitor_feedback"] = {
            "level": "success",
            "text": f"✅ Agora rastreando {new_o} → {new_d} por 24h.",
        }
        st.rerun()
    if c3.button("Cancelar", key="monitor_cancel", use_container_width=True):
        st.session_state.pop("monitor_conflict", None)
        st.rerun()


def render_monitor_prompt(config: dict) -> None:
    """Render "Deseja rastrear esta busca 24h?" with Sim/Não, persisting only the
    search configuration (never result history) and handling route conflicts via
    a Manter atual / Substituir / Cancelar dialog."""
    o = str(config.get("origin_iata") or "").upper()
    d = str(config.get("destination_iata") or "").upper()
    if not o or not d:
        return

    fb = st.session_state.pop("monitor_feedback", None)
    if fb:
        lvl = fb.get("level", "info")
        getattr(st, "success" if lvl == "success" else "info" if lvl == "info" else "warning")(fb["text"])

    conflict = st.session_state.get("monitor_conflict")
    if conflict and conflict.get("route_key") == _route_key(config):
        _render_replace_dialog(config, conflict["existing"])
        return

    st.markdown("**Deseja rastrear esta busca 24h?**")
    c1, c2 = st.columns(2)
    if c1.button("Sim, rastrear 24h", key="monitor_yes", type="primary", use_container_width=True):
        # st.rerun() lança uma exceção interna do Streamlit — chamado dentro do
        # `with session_scope()`, derruba a transação em rollback e a busca
        # nunca era gravada. Por isso a decisão acontece dentro da transação,
        # mas o rerun só dispara depois do commit.
        outcome: dict | None = None
        with session_scope() as db:
            existing = find_existing_monitor(db, o, d)
            if existing and existing.departure_date == config.get("departure_date"):
                outcome = {
                    "feedback": {
                        "level": "info",
                        "text": f"Você já está rastreando {o} → {d} nesta data.",
                    }
                }
            elif existing:
                outcome = {
                    "conflict": {
                        "existing": {
                            "origin_iata": existing.origin_iata,
                            "destination_iata": existing.destination_iata,
                            "departure_date": existing.departure_date,
                        },
                        "route_key": _route_key(config),
                    }
                }
            else:
                create_monitored_search(db, config)
                outcome = {
                    "feedback": {
                        "level": "success",
                        "text": f"✅ Rastreamento de 24h ativado para {o} → {d}.",
                    },
                    "created": True,
                }
        # TESTE TEMPORÁRIO: dispara uma mensagem de teste no Telegram (via
        # GitHub Actions, onde estão os secrets) para validar o canal de
        # alertas. Remover junto com telegram-test.yml depois que o teste
        # passar.
        if outcome and outcome.get("created"):
            from services.github_actions_service import trigger_telegram_test

            test = trigger_telegram_test()
            extra = (
                " 📨 Mensagem de teste enviada ao seu Telegram — deve chegar em até 1 minuto."
                if test.ok
                else f" ⚠️ Não consegui disparar o teste do Telegram: {test.message}"
            )
            outcome["feedback"]["text"] += extra
        if outcome and outcome.get("feedback"):
            st.session_state["monitor_feedback"] = outcome["feedback"]
        if outcome and outcome.get("conflict"):
            st.session_state["monitor_conflict"] = outcome["conflict"]
        st.rerun()
    if c2.button("Não", key="monitor_no", use_container_width=True):
        st.session_state["monitor_feedback"] = {"level": "info", "text": "Tudo bem — busca não será rastreada."}
        st.rerun()
