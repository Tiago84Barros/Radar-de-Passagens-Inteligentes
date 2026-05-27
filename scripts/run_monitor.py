from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.monitor import run_due_searches


if __name__ == "__main__":
    result = run_due_searches(force=False)
    print(f"Buscas checadas: {result['searches_checked']}")
    print(f"Cotações salvas: {result['quotes_saved']}")
