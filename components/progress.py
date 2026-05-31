"""'Andamento da execução' panel shown after a search.

Makes explicit that the API search is immediate while the GitHub Actions/worker
runs in parallel and may take longer. Shows a per-step timing bar chart.
"""
from __future__ import annotations

import time

import plotly.graph_objects as go
import streamlit as st

_TEAL = "#2DD4BF"
_BLUE = "#60A5FA"
_AMBER = "#FBBF24"
_MUTED = "#3b5168"

_WORKER_STATUS = {
    "queued": ("⏳ Na fila", _AMBER),
    "in_progress": ("🔄 Em execução", _BLUE),
    "completed": ("✅ Concluído", _TEAL),
    "failed": ("❌ Falhou", "#F87171"),
    "not_configured": ("➖ Não configurado", _MUTED),
    "unknown": ("❔ Desconhecido", _MUTED),
}


def render_execution_progress(progress: dict) -> None:
    """Render the execution-progress section from a stored ``search_progress`` dict."""
    if not progress:
        return

    api_s = float(progress.get("api_seconds") or 0)
    trigger_s = float(progress.get("trigger_seconds") or 0)
    worker_status = progress.get("worker_status") or "unknown"
    worker_est = float(progress.get("worker_estimate_seconds") or 0)
    started_at = float(progress.get("started_at") or time.time())
    elapsed = max(0.0, time.time() - started_at)

    status_label, status_color = _WORKER_STATUS.get(worker_status, _WORKER_STATUS["unknown"])
    worker_active = worker_status in {"queued", "in_progress"}

    # Current step (the API part is already finished by the time this renders).
    if worker_active:
        current_step = "Aguardando GitHub Actions/worker"
    elif worker_status == "completed":
        current_step = "Finalizado"
    else:
        current_step = "Finalizado (busca via API)"

    st.markdown('<div class="deals-section-header">📡 Andamento da execução</div>', unsafe_allow_html=True)

    c = st.columns(4)
    c[0].markdown(
        f'<div class="radar-card radar-rec"><div class="radar-card-label">Busca imediata (API)</div>'
        f'<div class="radar-card-value">✅ Concluída</div>'
        f'<div class="radar-card-sub">{api_s:.1f}s · {int(progress.get("saved") or 0)} cotações</div></div>',
        unsafe_allow_html=True,
    )
    c[1].markdown(
        f'<div class="radar-card radar-mon"><div class="radar-card-label">GitHub Actions/worker</div>'
        f'<div class="radar-card-value" style="color:{status_color}">{status_label}</div>'
        f'<div class="radar-card-sub">execução complementar</div></div>',
        unsafe_allow_html=True,
    )
    c[2].markdown(
        f'<div class="radar-card"><div class="radar-card-label">Tempo decorrido</div>'
        f'<div class="radar-card-value">{elapsed:.0f}s</div>'
        f'<div class="radar-card-sub">desde o clique</div></div>',
        unsafe_allow_html=True,
    )
    c[3].markdown(
        f'<div class="radar-card"><div class="radar-card-label">Etapa atual</div>'
        f'<div class="radar-card-value" style="font-size:1rem">{current_step}</div></div>',
        unsafe_allow_html=True,
    )

    # ── Per-step timing bar chart (horizontal) ────────────────────────────────
    steps = [
        ("Preparando busca", 0.3, _MUTED, False),
        ("Consultando API + salvando", max(api_s, 0.1), _TEAL, False),
        ("Acionando monitoramento", max(trigger_s, 0.1), _BLUE, False),
    ]
    if worker_active:
        steps.append(("Aguardando GitHub Actions/worker", worker_est or 90, _AMBER, True))

    labels = [s[0] for s in steps]
    values = [round(s[1], 1) for s in steps]
    colors = [s[2] for s in steps]
    estimated = [s[3] for s in steps]
    text = [f"~{v:.0f}s (estimado)" if est else f"{v:.1f}s" for v, est in zip(values, estimated)]

    fig = go.Figure(
        go.Bar(
            x=values, y=labels, orientation="h", marker_color=colors,
            text=text, textposition="auto",
            hovertemplate="%{y}: %{x:.1f}s<extra></extra>",
        )
    )
    fig.update_layout(
        height=240, margin=dict(l=8, r=8, t=10, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E5EDF8"), xaxis_title="segundos",
        yaxis=dict(autorange="reversed"),
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,.15)")
    st.plotly_chart(fig, use_container_width=True)

    if worker_active:
        st.caption(
            "⏳ Progresso estimado. O GitHub Actions pode concluir em alguns minutos. "
            "Os resultados imediatos acima já vêm da API — atualize a página em ~2-3 min "
            "para ver também o que o worker coletar."
        )
    elif worker_status == "not_configured":
        st.caption("Os resultados acima vêm 100% da API imediata. O worker complementar não está configurado.")
