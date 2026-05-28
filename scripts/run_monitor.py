from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.monitor import run_due_searches


if __name__ == "__main__":
    force = os.getenv("MONITOR_FORCE", "false").strip().lower() in {"1", "true", "yes", "sim", "on"}
    result = run_due_searches(force=force)
    print(f"Buscas checadas: {result['searches_checked']}")
    print(f"Cotações salvas: {result['quotes_saved']}")
