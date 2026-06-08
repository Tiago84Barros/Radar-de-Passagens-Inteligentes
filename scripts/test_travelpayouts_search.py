"""Testa o TravelPayoutsProvider isoladamente, fora do app.

Uso:
    set TRAVELPAYOUTS_API_TOKEN=seu-token   (Windows)
    export TRAVELPAYOUTS_API_TOKEN=seu-token   (Linux/Mac)
    python scripts/test_travelpayouts_search.py BEL MCO 2026-10-01 2026-10-08
"""
from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from providers.travelpayouts_provider import TravelPayoutsProvider, TravelPayoutsProviderError


def main() -> None:
    args = sys.argv[1:]
    origin = args[0] if len(args) > 0 else "BEL"
    destination = args[1] if len(args) > 1 else "MCO"
    departure = args[2] if len(args) > 2 else (date.today() + timedelta(days=120)).isoformat()
    return_date = args[3] if len(args) > 3 else None

    provider = TravelPayoutsProvider()
    print(f"is_configured(): {provider.is_configured()}")
    if not provider.is_configured():
        print("TRAVELPAYOUTS_API_TOKEN nao definido no ambiente. Configure e rode novamente.")
        return

    try:
        results = provider.search_flights(
            origin=origin,
            destination=destination,
            departure_date=departure,
            return_date=return_date,
        )
    except TravelPayoutsProviderError as exc:
        print(f"Erro: {exc} (status={getattr(exc, 'status_code', None)})")
        return

    print(f"{len(results)} resultado(s):")
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
