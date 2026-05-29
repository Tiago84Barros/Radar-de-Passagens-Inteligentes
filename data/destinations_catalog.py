from __future__ import annotations

# Set of major Brazilian airport IATA codes for national/international classification
BRAZIL_IATAS: frozenset[str] = frozenset({
    "GRU", "CGH", "VCP",        # São Paulo
    "GIG", "SDU",               # Rio de Janeiro
    "BSB",                      # Brasília
    "SSA",                      # Salvador
    "REC",                      # Recife
    "FOR",                      # Fortaleza
    "FLN",                      # Florianópolis
    "MAO",                      # Manaus
    "BEL",                      # Belém
    "IGU",                      # Foz do Iguaçu
    "CWB",                      # Curitiba
    "POA",                      # Porto Alegre
    "NAT",                      # Natal
    "MCZ",                      # Maceió
    "THE",                      # Teresina
    "CGR",                      # Campo Grande
    "CGB",                      # Cuiabá
    "SLZ",                      # São Luís
    "GYN",                      # Goiânia
    "VIX",                      # Vitória
    "JPA",                      # João Pessoa
    "AJU",                      # Aracaju
    "PMW",                      # Palmas
    "PVH",                      # Porto Velho
    "RBR",                      # Rio Branco
    "MCP",                      # Macapá
    "BVB",                      # Boa Vista
    "LDB",                      # Londrina
    "MGF",                      # Maringá
    "UDI",                      # Uberlândia
    "CNF", "PLU",               # Belo Horizonte
    "STM",                      # Santarém
    "IMP",                      # Imperatriz
    "CPV",                      # Campina Grande
    "JDO",                      # Juazeiro do Norte
    "IOS",                      # Ilhéus
    "BPS",                      # Porto Seguro
    "PNZ",                      # Petrolina
    "JOI",                      # Joinville
    "XAP",                      # Chapecó
    "OPS",                      # Sinop
})

# National gradient fallback (used when image fails to load)
_NATIONAL_GRADIENT = "linear-gradient(135deg, #0d3b2e 0%, #0a3347 60%, #07263a 100%)"
# International gradient fallback
_INTL_GRADIENT = "linear-gradient(135deg, #1a1060 0%, #2d1b69 60%, #0f0a3a 100%)"


DESTINATIONS: dict[str, dict] = {
    # ─────────────────────────────────────────────────────
    # NACIONAL
    # ─────────────────────────────────────────────────────
    "GIG": {
        "city": "Rio de Janeiro",
        "state": "RJ",
        "country": "Brasil",
        "iata": "GIG",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1483729558449-99ef09a8c325?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Cristo Redentor, Rio de Janeiro",
        "gradient": _NATIONAL_GRADIENT,
    },
    "SDU": {
        "city": "Rio de Janeiro",
        "state": "RJ",
        "country": "Brasil",
        "iata": "SDU",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1483729558449-99ef09a8c325?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Baía de Guanabara, Rio de Janeiro",
        "gradient": _NATIONAL_GRADIENT,
    },
    "GRU": {
        "city": "São Paulo",
        "state": "SP",
        "country": "Brasil",
        "iata": "GRU",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1549144511-f099e773c147?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Skyline de São Paulo",
        "gradient": _NATIONAL_GRADIENT,
    },
    "CGH": {
        "city": "São Paulo",
        "state": "SP",
        "country": "Brasil",
        "iata": "CGH",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1549144511-f099e773c147?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Avenida Paulista, São Paulo",
        "gradient": _NATIONAL_GRADIENT,
    },
    "SSA": {
        "city": "Salvador",
        "state": "BA",
        "country": "Brasil",
        "iata": "SSA",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1634654836293-39c83f026c5e?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Pelourinho, Salvador",
        "gradient": _NATIONAL_GRADIENT,
    },
    "REC": {
        "city": "Recife",
        "state": "PE",
        "country": "Brasil",
        "iata": "REC",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1574783144808-e1f97c62d1e8?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Marco Zero, Recife",
        "gradient": _NATIONAL_GRADIENT,
    },
    "FOR": {
        "city": "Fortaleza",
        "state": "CE",
        "country": "Brasil",
        "iata": "FOR",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1590407882764-ad59b5a39f3e?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Praia de Iracema, Fortaleza",
        "gradient": _NATIONAL_GRADIENT,
    },
    "FLN": {
        "city": "Florianópolis",
        "state": "SC",
        "country": "Brasil",
        "iata": "FLN",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1571816119732-23b29ace3a83?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Lagoa da Conceição, Florianópolis",
        "gradient": _NATIONAL_GRADIENT,
    },
    "IGU": {
        "city": "Foz do Iguaçu",
        "state": "PR",
        "country": "Brasil",
        "iata": "IGU",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1508519278310-ead7f90f7b87?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Cataratas do Iguaçu",
        "gradient": _NATIONAL_GRADIENT,
    },
    "MAO": {
        "city": "Manaus",
        "state": "AM",
        "country": "Brasil",
        "iata": "MAO",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1594212699903-ec8a3eca50f5?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Teatro Amazonas, Manaus",
        "gradient": _NATIONAL_GRADIENT,
    },
    "BSB": {
        "city": "Brasília",
        "state": "DF",
        "country": "Brasil",
        "iata": "BSB",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1577948000111-9c970dfe3743?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Congresso Nacional, Brasília",
        "gradient": _NATIONAL_GRADIENT,
    },
    "BEL": {
        "city": "Belém",
        "state": "PA",
        "country": "Brasil",
        "iata": "BEL",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1583853963305-8c5f8ef11b72?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Ver-o-Peso, Belém do Pará",
        "gradient": _NATIONAL_GRADIENT,
    },
    "CWB": {
        "city": "Curitiba",
        "state": "PR",
        "country": "Brasil",
        "iata": "CWB",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1584515933487-779824d29309?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Jardim Botânico, Curitiba",
        "gradient": _NATIONAL_GRADIENT,
    },
    "POA": {
        "city": "Porto Alegre",
        "state": "RS",
        "country": "Brasil",
        "iata": "POA",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1598908314732-07113901949e?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Orla do Guaíba, Porto Alegre",
        "gradient": _NATIONAL_GRADIENT,
    },
    "CNF": {
        "city": "Belo Horizonte",
        "state": "MG",
        "country": "Brasil",
        "iata": "CNF",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1598188306155-25b96e638787?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Praça da Liberdade, Belo Horizonte",
        "gradient": _NATIONAL_GRADIENT,
    },

    # ─────────────────────────────────────────────────────
    # INTERNACIONAL
    # ─────────────────────────────────────────────────────
    "LIS": {
        "city": "Lisboa",
        "country": "Portugal",
        "iata": "LIS",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1548707309-dcebeab9ea9b?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Elétrico 28, Lisboa",
        "gradient": _INTL_GRADIENT,
    },
    "CDG": {
        "city": "Paris",
        "country": "França",
        "iata": "CDG",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1499856871958-5b9627545d1a?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Torre Eiffel, Paris",
        "gradient": _INTL_GRADIENT,
    },
    "ORY": {
        "city": "Paris",
        "country": "França",
        "iata": "ORY",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1499856871958-5b9627545d1a?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Torre Eiffel, Paris",
        "gradient": _INTL_GRADIENT,
    },
    "LHR": {
        "city": "Londres",
        "country": "Reino Unido",
        "iata": "LHR",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Tower Bridge, Londres",
        "gradient": _INTL_GRADIENT,
    },
    "LGW": {
        "city": "Londres",
        "country": "Reino Unido",
        "iata": "LGW",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Big Ben, Londres",
        "gradient": _INTL_GRADIENT,
    },
    "EZE": {
        "city": "Buenos Aires",
        "country": "Argentina",
        "iata": "EZE",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1589909202802-8f4aab6e0716?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Obelisco, Buenos Aires",
        "gradient": _INTL_GRADIENT,
    },
    "AEP": {
        "city": "Buenos Aires",
        "country": "Argentina",
        "iata": "AEP",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1589909202802-8f4aab6e0716?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Caminito, Buenos Aires",
        "gradient": _INTL_GRADIENT,
    },
    "SCL": {
        "city": "Santiago",
        "country": "Chile",
        "iata": "SCL",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1568322445389-f64ac2515020?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Plaza de Armas, Santiago",
        "gradient": _INTL_GRADIENT,
    },
    "MIA": {
        "city": "Miami",
        "country": "EUA",
        "iata": "MIA",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1533106066535-ef4ad08a551e?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "South Beach, Miami",
        "gradient": _INTL_GRADIENT,
    },
    "MCO": {
        "city": "Orlando",
        "country": "EUA",
        "iata": "MCO",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1617719547972-4b4a91e4073c?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Walt Disney World, Orlando",
        "gradient": _INTL_GRADIENT,
    },
    "JFK": {
        "city": "Nova York",
        "country": "EUA",
        "iata": "JFK",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Manhattan, Nova York",
        "gradient": _INTL_GRADIENT,
    },
    "EWR": {
        "city": "Nova York",
        "country": "EUA",
        "iata": "EWR",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Estátua da Liberdade, Nova York",
        "gradient": _INTL_GRADIENT,
    },
    "FCO": {
        "city": "Roma",
        "country": "Itália",
        "iata": "FCO",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1515542143253-6c2a1f09bba5?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Coliseu, Roma",
        "gradient": _INTL_GRADIENT,
    },
    "MAD": {
        "city": "Madri",
        "country": "Espanha",
        "iata": "MAD",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1539037116277-4db20889f2d4?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Gran Vía, Madri",
        "gradient": _INTL_GRADIENT,
    },
    "BCN": {
        "city": "Barcelona",
        "country": "Espanha",
        "iata": "BCN",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1539037116277-4db20889f2d4?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Sagrada Família, Barcelona",
        "gradient": _INTL_GRADIENT,
    },
    "CUN": {
        "city": "Cancún",
        "country": "México",
        "iata": "CUN",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1552074284-5e88ef1aef18?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Zona Hotelera, Cancún",
        "gradient": _INTL_GRADIENT,
    },
    "BOG": {
        "city": "Bogotá",
        "country": "Colômbia",
        "iata": "BOG",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1588776813639-6e0e9db35aa0?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "La Candelaria, Bogotá",
        "gradient": _INTL_GRADIENT,
    },
    "LIM": {
        "city": "Lima",
        "country": "Peru",
        "iata": "LIM",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1531968455001-5c5272a41129?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Miraflores, Lima",
        "gradient": _INTL_GRADIENT,
    },
    "DXB": {
        "city": "Dubai",
        "country": "Emirados Árabes",
        "iata": "DXB",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1518684079-3c830dcef090?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Burj Khalifa, Dubai",
        "gradient": _INTL_GRADIENT,
    },
    "NRT": {
        "city": "Tóquio",
        "country": "Japão",
        "iata": "NRT",
        "category": "international",
        "image_url": "https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Shibuya, Tóquio",
        "gradient": _INTL_GRADIENT,
    },
    "NAT": {
        "city": "Natal",
        "state": "RN",
        "country": "Brasil",
        "iata": "NAT",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1593105544559-ecb03bf76f82?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Praia de Ponta Negra, Natal",
        "gradient": _NATIONAL_GRADIENT,
    },
    "MCZ": {
        "city": "Maceió",
        "state": "AL",
        "country": "Brasil",
        "iata": "MCZ",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1589330694653-ded6df03f754?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Praia de Pajuçara, Maceió",
        "gradient": _NATIONAL_GRADIENT,
    },
    "VCP": {
        "city": "Campinas",
        "state": "SP",
        "country": "Brasil",
        "iata": "VCP",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1554168848-228452c09d60?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Campinas, São Paulo",
        "gradient": _NATIONAL_GRADIENT,
    },
    "VIX": {
        "city": "Vitória",
        "state": "ES",
        "country": "Brasil",
        "iata": "VIX",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1591202468672-3a6c41f8a26b?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Vitória, Espírito Santo",
        "gradient": _NATIONAL_GRADIENT,
    },
    "PMW": {
        "city": "Palmas",
        "state": "TO",
        "country": "Brasil",
        "iata": "PMW",
        "category": "national",
        "image_url": "https://images.unsplash.com/photo-1516815231560-8f41ec531527?w=640&q=80&auto=format&fit=crop",
        "postcard_label": "Palmas, Tocantins",
        "gradient": _NATIONAL_GRADIENT,
    },
}


# Generic real travel photos used as postcard fallback for destinations that
# are not individually catalogued. Picked deterministically by IATA so the same
# airport always shows the same image. They are intentionally scenic/generic
# (not a specific landmark) so we never imply a wrong location.
_FALLBACK_NATIONAL_IMAGES: tuple[str, ...] = (
    "https://images.unsplash.com/photo-1483729558449-99ef09a8c325?w=640&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1516815231560-8f41ec531527?w=640&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1544989164-31dc3c645987?w=640&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1619546952812-520e98064a52?w=640&q=80&auto=format&fit=crop",
)
_FALLBACK_INTL_IMAGES: tuple[str, ...] = (
    "https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=640&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=640&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1500835556837-99ac94a94552?w=640&q=80&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?w=640&q=80&auto=format&fit=crop",
)


def _fallback_image(iata: str, is_national: bool) -> str:
    """Pick a stable generic travel photo for an uncatalogued destination."""
    pool = _FALLBACK_NATIONAL_IMAGES if is_national else _FALLBACK_INTL_IMAGES
    if not iata:
        return pool[0]
    idx = sum(ord(c) for c in iata) % len(pool)
    return pool[idx]


def get_destination_info(iata: str) -> dict:
    """Return destination metadata by IATA code. Falls back to a generic entry
    (with a stable travel photo) when the airport is not individually catalogued,
    so every destination card always renders a postcard image."""
    iata = (iata or "").upper().strip()
    if iata in DESTINATIONS:
        return DESTINATIONS[iata]
    is_national = iata in BRAZIL_IATAS
    return {
        "city": iata,
        "country": "Brasil" if is_national else "Internacional",
        "iata": iata,
        "category": "national" if is_national else "international",
        "image_url": _fallback_image(iata, is_national),
        "postcard_label": iata,
        "gradient": _NATIONAL_GRADIENT if is_national else _INTL_GRADIENT,
    }
