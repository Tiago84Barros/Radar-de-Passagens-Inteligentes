from datetime import date
from urllib.parse import parse_qs, urlparse

from services.official_search_links import build_official_search_links


def test_builds_azul_round_trip_search_link():
    links = build_official_search_links(
        {
            "origin_iata": "BEL",
            "destination_iata": "FOR",
            "departure_date": date(2026, 7, 25),
            "return_date": date(2026, 8, 1),
            "adults": 2,
        }
    )

    azul = next(link for link in links if link["label"] == "Azul")
    parsed = urlparse(azul["url"])
    params = parse_qs(parsed.query)

    assert parsed.netloc == "www.voeazul.com.br"
    assert params["c[0].ds"] == ["BEL"]
    assert params["c[0].as"] == ["FOR"]
    assert params["c[0].std"] == ["07/25/2026"]
    assert params["c[1].ds"] == ["FOR"]
    assert params["c[1].as"] == ["BEL"]
    assert params["c[1].std"] == ["08/01/2026"]
    assert params["p[0].c"] == ["2"]
    assert params["cc"] == ["BRL"]


def test_builds_one_way_search_links_without_return_segment():
    links = build_official_search_links(
        {
            "origin_iata": "BEL",
            "destination_iata": "FOR",
            "departure_date": "2026-07-25",
            "return_date": None,
            "adults": 1,
        }
    )

    azul = next(link for link in links if link["label"] == "Azul")
    params = parse_qs(urlparse(azul["url"]).query)

    assert params["c[0].std"] == ["07/25/2026"]
    assert "c[1].std" not in params
    assert {link["label"] for link in links} == {"Azul", "Google Flights", "Skyscanner", "Kayak"}
