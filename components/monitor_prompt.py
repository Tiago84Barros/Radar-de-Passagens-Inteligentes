from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from app.db import FlightSearch, session_scope
from utils.formatters import format_date_br


def _route_key(route: dict) -> str:
    o = str(route.get("origin_code") or "").upper()
    d = str(route.get("destination_code") or "").upper()
    dep = route.get("departure_date")
    return f"{o}->{d}@{dep}"


def _active_searches() -> list[dict]:
    """Return lightweight summaries of currently active searches."""
    with session_scope() as db:
        rows = list(
            db.scalars(select(FlightSearch).where(FlightSearch.is_active.is_(True)))
        )
        return [
            {
                "id": s.id,
                "origin": s.origin,
                "destination": s.destination,
                "departure_date": s.departure_date,
            }
            for s in rows
        ]


def _create_active_search(route: dict) -> None:
    with session_scope() as db:
        db.add(
            FlightSearch(
                owner_email="demo@radar.local",
                origin=str(route.get("origin_code") or "").upper(),
                destination=str(route.get("destination_code") or "").upper(),
                departure_date=route.get("departure_date"),
                return_date=route.get("return_date"),
                adults=int(route.get("adults") or 1),
                passengers=int(route.get("adults") or 1),
                max_price=float(route.get("max_price") or 3200.0),
                currency=str(route.get("currency") or "BRL"),
                trip_type=str(route.get("trip_type") or "round_trip"),
                frequency_minutes=int(route.get("frequency_minutes") or 60),
                is_active=True,
            )
        )


def _deactivate(search_id: int) -> None:
    with session_scope() as db:
        item = db.get(FlightSearch, search_id)
        if item:
            item.is_active = False


def _render_conflict(route: dict, conflict: dict) -> None:
    existing = conflict["existing"]
    o = existing["origin"]
    d = existing["destination"]
    when = format_date_br(existing.get("departure_date"))
    st.markdown(
        f'<div class="monitor-conflict">⚠️ Você já possui uma busca ativa: '
        f'<strong>{o} → {d}</strong> em <strong>{when}</strong>.<br>'
        f'Deseja manter a busca atual ou substituir pela nova rota?</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    if c1.button("Manter busca atual", key="monitor_keep", use_container_width=True):
        st.session_state.pop("monitor_conflict", None)
        st.session_state["monitor_feedback"] = {
            "level": "info",
            "text": f"Mantida a busca ativa atual: {o} → {d}.",
        }
        st.rerun()
    if c2.button("Substituir pela nova rota", key="monitor_replace", type="primary", use_container_width=True):
        _deactivate(existing["id"])
        _create_active_search(route)
        st.session_state.pop("monitor_conflict", None)
        new_o = str(route.get("origin_code") or "").upper()
        new_d = str(route.get("destination_code") or "").upper()
        st.session_state["monitor_feedback"] = {
            "level": "success",
            "text": f"✅ Busca anterior pausada. Agora monitorando {new_o} → {new_d} 24h.",
        }
        st.rerun()
    if c3.button("Cancelar", key="monitor_cancel", use_container_width=True):
        st.session_state.pop("monitor_conflict", None)
        st.rerun()


def render_monitor_prompt(route: dict) -> None:
    """Render the "Monitorar esta rota 24h" button with active-search conflict
    handling (keep / replace / cancel)."""
    o = str(route.get("origin_code") or "").upper()
    d = str(route.get("destination_code") or "").upper()
    if not o or not d:
        return

    # Show feedback from a previous action (survives st.rerun).
    fb = st.session_state.pop("monitor_feedback", None)
    if fb:
        lvl = fb.get("level", "info")
        getattr(st, "success" if lvl == "success" else "info" if lvl == "info" else "warning")(fb["text"])

    # If a conflict is pending for this exact route, render the chooser.
    conflict = st.session_state.get("monitor_conflict")
    if conflict and conflict.get("route_key") == _route_key(route):
        _render_conflict(route, conflict)
        return

    if st.button("🛰️ Monitorar esta rota 24h", key="monitor_btn", use_container_width=True):
        active = _active_searches()
        same = [s for s in active if s["origin"] == o and s["destination"] == d]
        others = [s for s in active if not (s["origin"] == o and s["destination"] == d)]
        if same:
            st.session_state["monitor_feedback"] = {
                "level": "info",
                "text": f"Você já está monitorando {o} → {d} 24h.",
            }
            st.rerun()
        elif others:
            st.session_state["monitor_conflict"] = {
                "existing": others[0],
                "route_key": _route_key(route),
            }
            st.rerun()
        else:
            _create_active_search(route)
            st.session_state["monitor_feedback"] = {
                "level": "success",
                "text": f"✅ Monitoramento 24h ativado para {o} → {d}.",
            }
            st.rerun()
