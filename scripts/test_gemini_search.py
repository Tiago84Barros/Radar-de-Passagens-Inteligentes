"""Testa o GeminiSearchProvider isoladamente, fora do app.

Mostra a resposta crua do Gemini (antes do parse/validacao) e o resultado
normalizado, para diagnosticar se o problema e falta de cobertura da busca
web ou um processo de parsing/validacao no app.

Uso:
    set GEMINI_API_KEY=sua-chave   (Windows)
    export GEMINI_API_KEY=sua-chave   (Linux/Mac)
    python scripts/test_gemini_search.py BEL MCO 2026-10-01 2026-10-08
"""
from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from providers.gemini_search_provider import GeminiSearchProvider, _parse_json_array


def main() -> None:
    args = sys.argv[1:]
    origin = args[0] if len(args) > 0 else "BEL"
    destination = args[1] if len(args) > 1 else "MCO"
    departure = args[2] if len(args) > 2 else (date.today() + timedelta(days=120)).isoformat()
    return_date = args[3] if len(args) > 3 else None

    provider = GeminiSearchProvider()

    print(f"is_configured(): {provider.is_configured()}")
    if not provider.is_configured():
        print("GEMINI_API_KEY nao definido no ambiente. Configure e rode novamente.")
        return

    prompt = _build_prompt_preview(origin, destination, departure, return_date)
    print(f"\n--- Prompt enviado ao Gemini ---\n{prompt}\n")

    print("--- Chamando _call_gemini (resposta crua, antes do parse) ---")
    raw_text = provider._call_gemini(prompt)
    print(raw_text or "<resposta vazia>")

    print("\n--- _parse_json_array(raw_text) ---")
    parsed = _parse_json_array(raw_text)
    print(parsed)

    print("\n--- search_flights() (resultado normalizado/validado) ---")
    results = provider.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure,
        return_date=return_date,
    )
    print(f"{len(results)} resultado(s):")
    for r in results:
        print(r)


def _build_prompt_preview(origin: str, destination: str, departure: str, return_date: str | None) -> str:
    from providers.gemini_search_provider import _build_user_prompt
    return _build_user_prompt(origin, destination, departure, return_date, adults=1, cabin="Economy")


if __name__ == "__main__":
    main()
