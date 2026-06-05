"""Teste de integração — Copa Air scraper e Amadeus API.

Executa as duas fontes novas para BEL -> MCO, 05/07/2026, 1 adulto.

Uso:
    python scripts/test_copa_amadeus.py

Variaveis de ambiente opcionais:
    AMADEUS_CLIENT_ID      — client ID do Amadeus (sandbox gratuito)
    AMADEUS_CLIENT_SECRET  — client secret do Amadeus

Saidas em outputs/:
    copa_result_<timestamp>.json
    amadeus_result_<timestamp>.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(exist_ok=True)

ORIGIN = "BEL"
DESTINATION = "MCO"
DEPARTURE = "2026-07-05"
RETURN = "2026-07-10"
ADULTS = 1

SEARCH_PARAMS = {
    "origin": ORIGIN,
    "destination": DESTINATION,
    "departure_date": DEPARTURE,
    "return_date": RETURN,
    "adults": ADULTS,
    "passengers": ADULTS,
    "currency": "BRL",
    "limit": 10,
}


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def save(name: str, data: dict) -> Path:
    stamp = ts()
    path = OUTPUTS / f"{name}_{stamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


# ── Copa Air ──────────────────────────────────────────────────────────────────

def run_copa() -> None:
    print("\n" + "=" * 55)
    print("Copa Air Scraper — BEL -> MCO | 05-10/07/2026")
    print("=" * 55)
    print("robots.txt Copa Air: User-agent: * Allow: /  (aberto)")

    try:
        from scrapers.copa_scraper import CopaAirScraper
    except ImportError as e:
        print(f"ERRO import: {e}")
        return

    scraper = CopaAirScraper()

    if not scraper._robots_allows(scraper.start_url):
        print("robots.txt nao permite acesso — abortando.")
        return

    print("robots.txt OK. Iniciando scraper...")
    try:
        results = scraper.search_flights(
            origin=ORIGIN,
            destination=DESTINATION,
            departure_date=DEPARTURE,
            return_date=RETURN,
            currency="USD",  # Copa opera em USD
            adults=ADULTS,
        )
    except Exception as exc:
        results = []
        print(f"Erro no scraper: {exc}")

    output = {
        "source": "copa_air",
        "search": SEARCH_PARAMS,
        "results_count": len(results),
        "results": results,
    }
    path = save("copa_result", output)

    if results:
        print(f"\n{len(results)} resultado(s) encontrado(s):")
        for r in results:
            print(f"  {r.get('airline','?')} | {r.get('price','?')} {r.get('currency','?')} "
                  f"| {r.get('duration_minutes','?')} min | {r.get('stops','?')} escala(s)")
    else:
        print("Nenhum resultado. Causas possiveis:")
        print("  - Playwright nao instalado (pip install playwright && playwright install chromium)")
        print("  - Site bloqueou o acesso neste ambiente")
        print("  - Rota sem disponibilidade para a data")
    print(f"Salvo em: {path}")


# ── Amadeus ───────────────────────────────────────────────────────────────────

def run_amadeus() -> None:
    print("\n" + "=" * 55)
    print("Amadeus API — BEL -> MCO | 05-10/07/2026")
    print("=" * 55)

    try:
        from services.amadeus_provider import AmadeusProvider, AmadeusConfigurationError, AmadeusConnectionError
    except ImportError as e:
        print(f"ERRO import: {e}")
        return

    amadeus = AmadeusProvider()

    if not amadeus.is_configured():
        print("Amadeus NAO configurado.")
        print("Para habilitar, configure em .env ou nos secrets:")
        print("  AMADEUS_CLIENT_ID=<seu_client_id>")
        print("  AMADEUS_CLIENT_SECRET=<seu_client_secret>")
        print("  AMADEUS_ENV=test  (sandbox gratuito)")
        print("\nCrie uma conta gratuita em: https://developers.amadeus.com")
        print("  1. Acesse Self-Service > My Apps > Create new app")
        print("  2. Copie Client ID e Client Secret")
        print("  3. No sandbox, Flight Offers Search esta disponivel gratuitamente")
        save("amadeus_result", {"configured": False, "results": []})
        return

    print(f"Amadeus configurado. Ambiente: {amadeus.settings.amadeus_env}")
    print("Obtendo token OAuth2...")

    try:
        token = amadeus.get_access_token()
        print(f"Token obtido: {token[:12]}...")
    except AmadeusConfigurationError as e:
        print(f"Erro de configuracao: {e}")
        return
    except AmadeusConnectionError as e:
        print(f"Erro de conexao: {e}")
        return

    print(f"Buscando voos {ORIGIN} -> {DESTINATION}...")
    try:
        results = amadeus.search_flights(SEARCH_PARAMS)
    except AmadeusConnectionError as e:
        print(f"Erro na busca: {e}")
        results = []

    output = {
        "source": "amadeus",
        "environment": amadeus.settings.amadeus_env,
        "search": SEARCH_PARAMS,
        "results_count": len(results),
        "results": results,
    }
    path = save("amadeus_result", output)

    if results:
        print(f"\n{len(results)} resultado(s) encontrado(s):")
        for r in results:
            print(f"  {r.get('airline','?')} | R$ {r.get('price','?')} "
                  f"| {r.get('duration_minutes','?')} min | {r.get('stops','?')} escala(s)")
    else:
        print("Nenhum resultado para essa rota no sandbox.")
        print("Nota: o sandbox Amadeus pode nao ter todos os mercados/rotas disponiveis.")

    print(f"Salvo em: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Radar de Passagens — Teste Copa Air + Amadeus")
    run_copa()
    run_amadeus()
    print("\nConcluido.")
