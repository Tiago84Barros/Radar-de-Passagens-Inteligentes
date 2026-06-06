"""Diagnostico do scraper Copa Air — BEL -> MCO.

Roda o Playwright de forma observavel (nao-headless opcional) e salva:
- outputs/copa_debug_network.json  : todos os endpoints JSON interceptados
- outputs/copa_debug_page.html     : HTML renderizado da pagina
- outputs/copa_debug_summary.txt   : resumo legivel

Objetivo: descobrir se a Copa serve dados de voo para BEL->MCO e em que formato,
para ajustar o parser do copa_scraper.py.

Uso:
    python scripts/debug_copa.py            # headless
    python scripts/debug_copa.py --show     # com janela visivel (melhor p/ ver bloqueio)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

ORIGIN, DEST = "BEL", "MCO"
DEP, RET = "2026-07-05", "2026-07-10"
CURRENCY = "USD"
SHOW = "--show" in sys.argv

RESULTS_URL = (
    "https://www.copaair.com/en-gs/book/flights/results/"
    f"?origin={ORIGIN}&destination={DEST}&departureDate={DEP}"
    f"&returnDate={RET}&adults=1&children=0&infants=0&cabin=Y&tripType=RT&currency={CURRENCY}"
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

FLIGHT_KEYWORDS = (
    "totalFare", "totalAmount", "flightOffers", "itinerary", "fareBasis",
    "cabin", "departureDate", "carrierCode", "flightSegment", "pricingInfo",
    "journeys", "fareInfo", "recommendation", "milesAmount", "price",
)


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERRO: Playwright nao instalado. Rode: pip install playwright && playwright install chromium")
        return

    print(f"Abrindo Copa Air: {ORIGIN} -> {DEST} | {DEP} a {RET}")
    print(f"URL: {RESULTS_URL}")
    print(f"Modo: {'janela visivel' if SHOW else 'headless'}\n")

    network: list[dict] = []
    all_json_urls: list[str] = []

    def on_response(response) -> None:
        url = response.url
        try:
            ct = response.headers.get("content-type", "")
        except Exception:
            ct = ""
        is_json = "json" in ct
        if is_json:
            all_json_urls.append(f"[{response.status}] {url}")
        if not is_json or response.status != 200:
            return
        try:
            body = response.text()
        except Exception:
            return
        has_kw = [kw for kw in FLIGHT_KEYWORDS if kw in body]
        if has_kw:
            network.append({
                "url": url,
                "status": response.status,
                "matched_keywords": has_kw,
                "body_len": len(body),
                "body_sample": body[:3000],
            })

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not SHOW)
        ctx = browser.new_context(
            user_agent=UA, locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        page.on("response", on_response)

        nav_status = "ok"
        try:
            page.goto(RESULTS_URL, wait_until="domcontentloaded", timeout=40_000)
        except Exception as e:
            nav_status = f"goto erro: {e}"

        # Da tempo para a SPA carregar os resultados via XHR
        try:
            page.wait_for_timeout(12_000)
        except Exception:
            pass

        # Tenta esperar por algum indicio de preco no DOM
        price_in_dom = False
        try:
            page.wait_for_selector("text=/\\$\\s?\\d/", timeout=8_000)
            price_in_dom = True
        except Exception:
            pass

        final_url = page.url
        title = page.title()
        try:
            html = page.content()
        except Exception:
            html = ""
        try:
            body_text = page.locator("body").inner_text(timeout=5_000)
        except Exception:
            body_text = ""

        browser.close()

    # ── Salva artefatos ──────────────────────────────────────────────────────
    (OUT / "copa_debug_page.html").write_text(html, encoding="utf-8")
    (OUT / "copa_debug_network.json").write_text(
        json.dumps(network, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Detecta sinais de bloqueio
    block_signals = []
    low = (html + body_text).lower()
    for sig in ("captcha", "access denied", "are you a robot", "akamai",
                "cloudflare", "blocked", "unusual traffic", "forbidden",
                "px-captcha", "perimeterx", "datadome"):
        if sig in low:
            block_signals.append(sig)

    # Precos no texto
    usd_prices = sorted(set(
        float(m.replace(",", "")) for m in re.findall(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)", body_text)
        if m
    ))[:20]

    summary = []
    summary.append(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    summary.append(f"URL final: {final_url}")
    summary.append(f"Titulo da pagina: {title}")
    summary.append(f"Navegacao: {nav_status}")
    summary.append(f"HTML length: {len(html)}")
    summary.append(f"Body text length: {len(body_text)}")
    summary.append(f"Preco visivel no DOM (seletor): {price_in_dom}")
    summary.append(f"Precos $ extraidos do texto: {usd_prices}")
    summary.append(f"Sinais de bloqueio detectados: {block_signals or 'nenhum'}")
    summary.append(f"")
    summary.append(f"Endpoints JSON com palavras-chave de voo: {len(network)}")
    for n in network:
        summary.append(f"  - [{n['status']}] {n['url'][:120]}")
        summary.append(f"      keywords={n['matched_keywords']} len={n['body_len']}")
    summary.append(f"")
    summary.append(f"TODOS os endpoints JSON ({len(all_json_urls)}):")
    for u in all_json_urls[:60]:
        summary.append(f"  {u[:140]}")

    summary_txt = "\n".join(summary)
    (OUT / "copa_debug_summary.txt").write_text(summary_txt, encoding="utf-8")

    print(summary_txt)
    print(f"\nArtefatos salvos em: {OUT}")
    print("  - copa_debug_summary.txt")
    print("  - copa_debug_network.json")
    print("  - copa_debug_page.html")


if __name__ == "__main__":
    main()
