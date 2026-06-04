"""Route viability scoring for scraped flight quotes.

Scores a quote 0-100 across five dimensions:
  - Price competitiveness  (up to 40 pts)
  - Trip duration           (up to 25 pts)
  - Number of stops         (up to 20 pts)
  - Source reliability      (up to 10 pts)
  - Booking link available  (up to  5 pts)

Returns a dict with viability_score, label, and human-readable reasons.
"""
from __future__ import annotations

SCRAPER_SOURCES = {"azul", "gol", "latam", "google_flights"}
API_SOURCES = {"travelpayouts"}

VIABILITY_LABELS = {
    (80, 101): "Melhor rota",
    (60, 80): "Boa rota",
    (40, 60): "Viável",
    (0, 40): "Pouco viável",
}


def _label(score: int) -> str:
    for (lo, hi), label in VIABILITY_LABELS.items():
        if lo <= score < hi:
            return label
    return "Pouco viável"


def calculate_route_viability(quote: dict) -> dict:
    """Score a single quote and return viability info.

    ``quote`` may use either the raw scraper field names (price, provider,
    duration_minutes, stops, booking_link) or the display names used in the
    DataFrame built by streamlit_app.quotes_df (preço, provedor, duração_min,
    escalas, link).  Both forms are checked.
    """
    score = 0
    reasons: list[str] = []

    # ── Price (up to 40 pts) ────────────────────────────────────────────────
    price = float(quote.get("price") or quote.get("preço") or 0)
    if price > 0:
        if price <= 500:
            p = 40; reasons.append("Preço muito competitivo (≤ R$ 500)")
        elif price <= 1_000:
            p = 35; reasons.append("Preço competitivo (≤ R$ 1.000)")
        elif price <= 2_000:
            p = 25
        elif price <= 3_500:
            p = 12
        else:
            p = 4
    else:
        p = 0
    score += p

    # ── Duration (up to 25 pts) ─────────────────────────────────────────────
    mins = int(quote.get("duration_minutes") or quote.get("duração_min") or 0)
    if mins > 0:
        hours = mins / 60
        if hours <= 2:
            d = 25; reasons.append("Voo muito curto (≤ 2h)")
        elif hours <= 4:
            d = 22; reasons.append("Boa duração (≤ 4h)")
        elif hours <= 8:
            d = 17
        elif hours <= 12:
            d = 10
        elif hours <= 16:
            d = 5
        else:
            d = 2
    else:
        d = 12  # unknown → neutral
    score += d

    # ── Stops (up to 20 pts) ────────────────────────────────────────────────
    stops = int(quote.get("stops") or quote.get("escalas") or 0)
    if stops == 0:
        s = 20; reasons.append("Voo direto")
    elif stops == 1:
        s = 12; reasons.append("1 conexão")
    else:
        s = 4
    score += s

    # ── Source reliability (up to 10 pts) ───────────────────────────────────
    source = str(
        quote.get("provider") or quote.get("provedor") or quote.get("source") or ""
    ).lower().strip()
    if source in SCRAPER_SOURCES | API_SOURCES:
        r = 10; reasons.append(f"Fonte confiável ({source})")
    elif any(m in source for m in ("demo", "mock", "fallback")):
        r = 2
    else:
        r = 6
    score += r

    # ── Booking link (up to 5 pts) ──────────────────────────────────────────
    link = str(quote.get("booking_link") or quote.get("link") or "").strip()
    if link and link.startswith("http"):
        score += 5; reasons.append("Link de compra disponível")

    score = min(100, score)
    return {
        "viability_score": score,
        "label": _label(score),
        "reasons": reasons,
    }


def score_quotes(quotes: list[dict]) -> list[dict]:
    """Add viability fields to each quote dict in-place and return the list."""
    for q in quotes:
        v = calculate_route_viability(q)
        q["viability_score"] = v["viability_score"]
        q["viability_label"] = v["label"]
        q["viability_reasons"] = v["reasons"]
    return quotes


def best_route(quotes: list[dict]) -> dict | None:
    """Return the quote with the highest viability score, or None if empty."""
    if not quotes:
        return None
    return max(quotes, key=lambda q: q.get("viability_score", 0))
