from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.monitoring_bot import run_due_monitors


if __name__ == "__main__":
    force = os.getenv("MONITOR_FORCE", "false").strip().lower() in {"1", "true", "yes", "sim", "on"}
    result = run_due_monitors(force=force)
    print(
        f"Buscas no banco: {result.get('total_in_db', '?')} "
        f"(ativas: {result.get('active', '?')}, em rastreio até a viagem: {result.get('in_window', '?')})"
    )
    print(f"Buscas monitoradas verificadas: {result['monitors_checked']}")
    print(f"Alertas enviados: {result['alerts_sent']}")
    print(f"Atualizacoes de disponibilidade: {result.get('availability_updates', 0)}")
    if result.get("errors"):
        print(f"Buscas com erro: {result['errors']}")
