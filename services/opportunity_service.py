from __future__ import annotations

from datetime import date

import pandas as pd

from data.demo_deals import get_demo_international_deals, get_demo_national_deals
from data.destinations_catalog import BRAZIL_IATAS, get_destination_info
from services.miles_service import DEFAULT_CENTS_PER_MILE, enrich_deal_with_miles


def _classify_route(origin_iata: str, destination_iata: str) -> str:
    """Return 'national' if both airports are in Brazil, else 'international'."""
    o = (origin_iata or "").upper()
    d = (destination_iata or "").upper()
    if o in BRAZIL_IATAS and d in BRAZIL_IATAS:
        return "national"
    return "international"


def _df_row_to_deal(row: pd.Series) -> dict:
    """Convert a quotes DataFrame row into the standard deal dict."""
    origin_iata = str(row.get("origem") or "").upper()
    dest_iata = str(row.get("destino") or "").upper()
    dest_info = get_destination_info(dest_iata)
    orig_info = get_destination_info(origin_iata)
    price = float(row.get("preço") or 0)

    # Normalize dates
    dep = row.get("ida")
    ret = row.get("volta")
    if dep is not None and not isinstance(dep, date):
        try:
            dep = pd.to_datetime(dep).date()
        except Exception:
            dep = None
    if ret is not None and not isinstance(ret, date):
        try:
            ret = pd.to_datetime(ret).date()
        except Exception:
            ret = None

    classification = str(row.get("classificação") or row.get("oportunidade") or "")

    return {
        "id": f"real_{row.get('id', 'x')}",
        "origin_city": orig_info.get("city", origin_iata),
        "origin_iata": origin_iata,
        "destination_city": dest_info.get("city", dest_iata),
        "destination_iata": dest_iata,
        "destination_country": dest_info.get("country", ""),
        "departure_date": dep,
        "return_date": ret,
        "price_brl": price,
        "airline": str(row.get("companhia") or ""),
        "score": int(row.get("score") or 0),
        "classification": classification,
        "category": _classify_route(origin_iata, dest_iata),
        "provider": str(row.get("provedor") or ""),
        "booking_link": str(row.get("link") or ""),
        "is_demo": False,
        "stops": row.get("escalas"),
        "duration_minutes": row.get("duração_min"),
        "via_hub": str(row.get("via_hub") or ""),
        # Destination visual fields
        "image_url": dest_info.get("image_url", ""),
        "postcard_label": dest_info.get("postcard_label", ""),
        "gradient": dest_info.get("gradient", ""),
    }


def _enrich_demo(deal: dict, cents_per_mile: float = DEFAULT_CENTS_PER_MILE) -> dict:
    """Add destination visual info and miles to a demo deal."""
    dest_info = get_destination_info(deal["destination_iata"])
    return enrich_deal_with_miles(
        {
            **deal,
            "destination_country": dest_info.get("country", ""),
            "image_url": dest_info.get("image_url", ""),
            "postcard_label": dest_info.get("postcard_label", ""),
            "gradient": dest_info.get("gradient", ""),
        },
        cents_per_mile,
    )


def get_home_deals(
    df_quotes: pd.DataFrame,
    cents_per_mile: float = DEFAULT_CENTS_PER_MILE,
    national_limit: int = 5,
    international_limit: int = 5,
    fill_demo: bool = True,
) -> tuple[list[dict], list[dict]]:
    """
    Return (national_deals, international_deals) for the home screen.

    Uses real DB quotes when available. When ``fill_demo`` is True, gaps are
    filled with demo data (legacy behaviour, kept for tests). When False, only
    real quotes are returned so the UI can render "Dados Ausentes" — this is the
    mode the app uses, to make the screen reflect only real collected data.
    Each deal is enriched with destination info and miles estimation.
    """
    national: list[dict] = []
    international: list[dict] = []

    if not df_quotes.empty:
        # Drop rows without price or destination
        valid = df_quotes.dropna(subset=["preço", "destino"]).copy()
        valid = valid[valid["preço"] > 0]

        # Keep only future or recent quotes
        if "ida" in valid.columns:
            today = pd.Timestamp(date.today())
            valid["_dep_dt"] = pd.to_datetime(valid["ida"], errors="coerce")
            valid = valid[valid["_dep_dt"].isna() | (valid["_dep_dt"] >= today)]

        # Best price per (origin, destination) pair
        if not valid.empty:
            best_idx = valid.groupby(["origem", "destino"])["preço"].idxmin()
            best = valid.loc[best_idx].copy()
            best["_score"] = best.get("score", 0).fillna(0)
            best = best.sort_values("_score", ascending=False)

            for _, row in best.iterrows():
                deal = _df_row_to_deal(row)
                deal = enrich_deal_with_miles(deal, cents_per_mile)
                if deal["category"] == "national" and len(national) < national_limit:
                    national.append(deal)
                elif deal["category"] == "international" and len(international) < international_limit:
                    international.append(deal)

                if len(national) >= national_limit and len(international) >= international_limit:
                    break

    # Fill gaps with demo data only when explicitly allowed (legacy / tests).
    if fill_demo:
        demo_nat = [_enrich_demo(d, cents_per_mile) for d in get_demo_national_deals()]
        demo_int = [_enrich_demo(d, cents_per_mile) for d in get_demo_international_deals()]

        while len(national) < national_limit and demo_nat:
            national.append(demo_nat.pop(0))

        while len(international) < international_limit and demo_int:
            international.append(demo_int.pop(0))

    return national[:national_limit], international[:international_limit]


def get_airline_comparison(
    df_quotes: pd.DataFrame,
    origin: str,
    destination: str,
    cents_per_mile: float = DEFAULT_CENTS_PER_MILE,
) -> list[dict]:
    """
    Return the cheapest deal per airline for a specific route, sorted
    ascending by price (cheapest first). Each deal is enriched with miles.

    Used by the home-screen airline comparison card. Returns [] when there
    are no quotes for the route yet.
    """
    if df_quotes.empty or "preço" not in df_quotes.columns:
        return []

    o = (origin or "").upper()
    d = (destination or "").upper()
    route = df_quotes.dropna(subset=["preço"]).copy()
    route = route[
        (route["origem"].astype(str).str.upper() == o)
        & (route["destino"].astype(str).str.upper() == d)
        & (route["preço"] > 0)
    ]
    if route.empty:
        return []

    # Keep only future or undated quotes
    if "ida" in route.columns:
        today = pd.Timestamp(date.today())
        route["_dep_dt"] = pd.to_datetime(route["ida"], errors="coerce")
        route = route[route["_dep_dt"].isna() | (route["_dep_dt"] >= today)]
    if route.empty:
        return []

    # Normalize airline label so "" / NaN don't collapse into one bogus group
    route["_airline"] = route["companhia"].fillna("").astype(str).str.strip()
    route.loc[route["_airline"] == "", "_airline"] = "Não informada"

    cheapest_idx = route.groupby("_airline")["preço"].idxmin()
    cheapest = route.loc[cheapest_idx].sort_values("preço")

    deals: list[dict] = []
    for _, row in cheapest.iterrows():
        deal = _df_row_to_deal(row)
        deal = enrich_deal_with_miles(deal, cents_per_mile)
        deals.append(deal)
    return deals


def get_national_lowest(df_quotes: pd.DataFrame) -> float | None:
    """Return the lowest national price from the quotes DataFrame."""
    if df_quotes.empty or "preço" not in df_quotes.columns:
        return None
    valid = df_quotes.dropna(subset=["preço", "origem", "destino"])
    national = valid[valid.apply(
        lambda r: _classify_route(str(r["origem"]), str(r["destino"])) == "national", axis=1
    )]
    if national.empty:
        return None
    return float(national["preço"].min())


def get_international_lowest(df_quotes: pd.DataFrame) -> float | None:
    """Return the lowest international price from the quotes DataFrame."""
    if df_quotes.empty or "preço" not in df_quotes.columns:
        return None
    valid = df_quotes.dropna(subset=["preço", "origem", "destino"])
    intl = valid[valid.apply(
        lambda r: _classify_route(str(r["origem"]), str(r["destino"])) == "international", axis=1
    )]
    if intl.empty:
        return None
    return float(intl["preço"].min())


def get_best_miles_deal(df_quotes: pd.DataFrame, cents_per_mile: float = DEFAULT_CENTS_PER_MILE) -> dict | None:
    """Return the deal with the best miles value (lowest price per mile)."""
    if df_quotes.empty or "preço" not in df_quotes.columns:
        return None
    valid = df_quotes.dropna(subset=["preço"]).copy()
    valid = valid[valid["preço"] > 0]
    if valid.empty:
        return None
    best_row = valid.loc[valid["preço"].idxmin()]
    deal = _df_row_to_deal(best_row)
    return enrich_deal_with_miles(deal, cents_per_mile)
