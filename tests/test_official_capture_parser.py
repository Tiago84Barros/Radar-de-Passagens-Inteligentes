from services.official_capture_parser import parse_azul_visible_fares


AZUL_TEXT = """
06:45
BEL
Voo 4181 Direto
08:40
FOR
Duração: 1h 55m
A partir de
R$3.945,35
Ver tarifas

18:00
BEL
Voo 4101 Direto
19:55
FOR
Duração: 1h 55m
A partir de
R$2.486,35
Ver tarifas

01:30
BEL
1 conexão • Voo 4054
12:00
FOR
Duração: 10h 30m
A partir de
R$3.768,44
"""


def test_parse_azul_visible_fares_from_copied_results():
    fares = parse_azul_visible_fares(
        AZUL_TEXT,
        origin="BEL",
        destination="FOR",
        departure_date="2026-06-27",
        source_url="https://www.voeazul.com.br/br/pt/home/selecao-voo?c[0].ds=BEL",
    )

    assert [fare["price"] for fare in fares] == [2486.35, 3768.44, 3945.35]
    cheapest = fares[0]
    assert cheapest["provider"] == "captura_assistida_azul"
    assert cheapest["source_confidence"] == "verified"
    assert cheapest["origin"] == "BEL"
    assert cheapest["destination"] == "FOR"
    assert cheapest["departure_at"] == "2026-06-27T18:00:00"
    assert cheapest["duration_minutes"] == 115
    assert cheapest["stops"] == 0
    assert cheapest["flight_number"] == "4101"
    assert cheapest["booking_link"].startswith("https://www.voeazul.com.br/")


def test_parse_azul_visible_fares_rejects_wrong_source_or_route():
    assert parse_azul_visible_fares(
        AZUL_TEXT,
        origin="BEL",
        destination="FOR",
        departure_date="2026-06-27",
        source_url="https://example.com/fake",
    ) == []
    assert parse_azul_visible_fares(
        AZUL_TEXT,
        origin="FOR",
        destination="BEL",
        departure_date="2026-06-27",
        source_url="https://www.voeazul.com.br/br/pt/home/selecao-voo",
    ) == []
