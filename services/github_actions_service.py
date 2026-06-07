from __future__ import annotations

"""Trigger the monitoring-bot workflow on GitHub Actions from the Streamlit app.

The bot runs on a schedule in ``monitor-searches.yml`` (every 4h). This module
lets the "Executar agora" action fire that workflow on demand via the REST API
(``workflow_dispatch``), so a fresh check is picked up within seconds instead of
waiting for the next cron tick.

Important: triggering here does NOT replace the cron. The schedule keeps running
independently, so monitoring continues even with the app closed. This is purely
an extra "run now" nudge.
"""

from dataclasses import dataclass

import requests

from app.settings import get_settings

_API_BASE = "https://api.github.com"
_TIMEOUT = 15


@dataclass
class DispatchResult:
    ok: bool
    message: str


def is_configured() -> bool:
    """True when both GITHUB_TOKEN and GITHUB_REPO are set."""
    s = get_settings()
    return bool(s.github_token and s.github_repo)


def trigger_monitor(force: bool = True) -> DispatchResult:
    """Fire the monitor workflow via workflow_dispatch.

    Returns a DispatchResult describing the outcome. Never raises — the search
    must still succeed (and stay saved in the DB) even if the trigger fails, in
    which case the scheduled cron will pick it up later.
    """
    s = get_settings()
    if not s.github_token or not s.github_repo:
        return DispatchResult(
            ok=False,
            message="GITHUB_TOKEN/GITHUB_REPO não configurados — o monitor agendado coletará em até 30 min.",
        )

    url = f"{_API_BASE}/repos/{s.github_repo}/actions/workflows/{s.github_workflow}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {s.github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "ref": s.github_ref,
        "inputs": {"force": "true" if force else "false"},
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException as exc:  # network error — non-fatal
        return DispatchResult(ok=False, message=f"Falha de rede ao acionar o GitHub Actions: {exc}")

    if resp.status_code == 204:
        return DispatchResult(ok=True, message="Coleta acionada no GitHub Actions (resultado em ~2-3 min).")

    # Surface common, actionable errors without leaking the token
    detail = ""
    try:
        detail = resp.json().get("message", "")
    except Exception:  # noqa: BLE001
        detail = (resp.text or "")[:160]

    if resp.status_code == 401:
        msg = "Token do GitHub inválido ou expirado (401). Verifique o secret GITHUB_TOKEN."
    elif resp.status_code == 403:
        msg = "Sem permissão para acionar o workflow (403). O token precisa do escopo 'workflow'/'actions:write'."
    elif resp.status_code == 404:
        msg = (
            "Workflow ou repositório não encontrado (404). Confira GITHUB_REPO "
            f"('{s.github_repo}') e GITHUB_WORKFLOW ('{s.github_workflow}')."
        )
    elif resp.status_code == 422:
        msg = (
            "GitHub recusou o disparo (422). Confirme que monitor.yml tem 'workflow_dispatch' "
            f"e que o branch '{s.github_ref}' existe."
        )
    else:
        msg = f"GitHub retornou {resp.status_code}: {detail}"
    return DispatchResult(ok=False, message=msg)
