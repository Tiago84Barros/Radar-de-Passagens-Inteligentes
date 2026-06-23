"""Gemini + Google Search provider — busca passagens via pesquisa web em tempo real.

Mesmo racional do ClaudeSearchProvider: evita dependencia de scraping (bloqueado
por anti-bot) e de APIs pagas de voo. O Gemini usa a ferramenta de grounding
`google_search` (server-side) para pesquisar tarifas reais e responde em JSON
estruturado, validado com Pydantic antes de normalizar para o formato comum
dos providers. Roda com a mesma chave (`GEMINI_API_KEY`) ja usada em
price_alert_bot.py — sem custo adicional de configuracao.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError

from app.settings import get_settings
from providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

# Filtro de plausibilidade contra alucinação das IAs de busca. Às vezes o modelo
# inventa uma sequência arrumadinha de valores em escala errada (ex.: R$ 1,90 em
# vez de R$ 1.900, ou "35 milhas" em vez de 35.000). Nenhuma passagem real custa
# menos que isto, e prêmio em milhas é sempre na casa dos milhares — abaixo
# disso, descartamos o dado em vez de exibir lixo.
MIN_PLAUSIBLE_PRICE_BRL = 50.0
MIN_PLAUSIBLE_MILES = 1000

# Links sugeridos por IA só viram botões quando apontam para domínios oficiais
# conhecidos. A oferta continua visível sem link quando o domínio não passa
# nesta lista, evitando transformar texto gerado pelo modelo em redirecionamento
# arbitrário.
OFFICIAL_BOOKING_DOMAINS = {
    "aa.com",
    "aeromexico.com",
    "aircanada.com",
    "airfrance.com",
    "aireuropa.com",
    "avianca.com",
    "azul.com.br",
    "britishairways.com",
    "copaair.com",
    "delta.com",
    "emirates.com",
    "flytap.com",
    "gol.com.br",
    "iberia.com",
    "jetblue.com",
    "klm.com",
    "latam.com",
    "latamairlines.com",
    "lufthansa.com",
    "qatarairways.com",
    "southwest.com",
    "turkishairlines.com",
    "united.com",
    "tapairportugal.com",
    "voeazul.com.br",
    "voegol.com.br",
}

# Modelo principal e, em caso de quota esgotada (429 RESOURCE_EXHAUSTED) ou
# modelo descontinuado (404 NOT_FOUND — ex.: gemini-2.0-flash aposentado),
# modelos alternativos para tentar antes de desistir e cair para o proximo
# motor (OpenAI/Travelpayouts).
DEFAULT_MODEL = "gemini-2.5-flash"
FALLBACK_MODELS = ["gemini-2.5-flash-lite", "gemini-flash-latest"]

SYSTEM_PROMPT = (
    "Voce e um comprador experiente de passagens aereas pesquisando para si "
    "mesmo. Voce SOMENTE reporta precos encontrados de fato na busca do Google "
    "nesta sessao — nunca estima, arredonda ou completa com 'conhecimento "
    "previo'. Cada item da resposta tem que vir de uma pagina real visitada "
    "durante esta pesquisa.\n\n"
    "Estrategia de busca obrigatoria (faca VARIAS consultas, nunca uma so):\n"
    "1. Pesquise o trecho pedido em pelo menos 4 fontes distintas, priorizando: "
    "Google Flights, Skyscanner, Kayak, Decolar e o site oficial das "
    "companhias relevantes para a rota (LATAM, GOL, Azul, TAP, Iberia, "
    "Air Europa, American, United, Delta, Copa, Avianca, Air France/KLM, "
    "conforme o trecho).\n"
    "2. Varie a formulacao a cada tentativa em vez de repetir a mesma busca, "
    "por exemplo: '<origem> <destino> <data> passagem aerea preco', "
    "'flights <ORIGEM> to <DESTINO> <data> price', "
    "'<origem> <destino> <data> google flights', "
    "'site:latam.com <origem> <destino>'. Buscas genericas tendem a trazer "
    "paginas antigas ou sem preco — refine ate achar uma pagina com tarifa e "
    "data explicitas.\n"
    "3. DATAS: o intervalo de dias pedido e sagrado. Se o usuario pediu "
    "ida 10/07 e volta 17/07 (7 dias de viagem), so devolva itinerarios com "
    "essa mesma duracao de viagem. Se nao achar nada para as datas exatas, "
    "deslize a janela INTEIRA em ate 2 dias (ex.: 11/07-18/07), mantendo o "
    "mesmo numero de dias — nunca devolva datas aleatorias so porque estao "
    "baratas. Marque sempre a data realmente encontrada.\n"
    "4. VARIEDADE: nao se limite as opcoes mais baratas. Devolva um mix "
    "explicito: as 2-3 mais baratas (categoria 'mais_barata'), as 2-3 mais "
    "rapidas/menos conexoes (categoria 'mais_rapida') e 1-2 com melhor "
    "equilibrio preco x tempo (categoria 'equilibrada').\n"
    "5. CONEXOES: para cada itinerario, liste cada conexao com o aeroporto e "
    "o tempo de espera em minutos (ex.: GRU, 95 min). Se o voo e direto, "
    "'conexoes' e uma lista vazia. Para trechos internacionais saindo do "
    "Brasil sem voo direto barato, pesquise itinerarios via grandes hubs "
    "(Lisboa, Madri, Miami, Nova York, Atlanta, Panama, Bogota, Lima, "
    "Santiago, Dubai, Istambul, Doha — conforme a regiao do destino).\n"
    "6. PRECOS IDA/VOLTA: em viagens de ida e volta, alem do total, procure o "
    "valor de cada trecho no detalhamento da tarifa (Google Flights e os "
    "sites das companhias mostram) e preencha 'preco_ida_brl' e "
    "'preco_volta_brl' quando encontrar. ATENCAO: a falta do detalhamento "
    "NUNCA e motivo para omitir um itinerario — devolva o item com o "
    "preco_total_brl e os trechos como null. Nunca divida o total por 2 nem "
    "repita o total em um dos trechos.\n"
    "7. MILHAS: pesquise tambem o preco em milhas nos programas das "
    "companhias encontradas (Smiles para GOL, Latam Pass para LATAM, TudoAzul "
    "para Azul, AAdvantage para American etc.). Se achar, preencha 'milhas' "
    "com programa, quantidade e taxas em BRL. Se nao achar, deixe null.\n"
    "8. LINK: o campo 'link' deve apontar para o SITE OFICIAL DA COMPANHIA "
    "AEREA que opera o voo (ex.: latam.com, voegol.com.br, voeazul.com.br, "
    "aa.com, delta.com) — nunca para agencia ou intermediario. Se voce achou "
    "o preco num agregador, inclua o agregador apenas em 'fonte' e monte o "
    "link da companhia para a rota/data. Companhia sempre pelo NOME COMPLETO "
    "(ex.: 'LATAM Airlines', 'GOL Linhas Aereas', 'Azul Linhas Aereas') — "
    "nunca sigla ou codigo IATA.\n"
    "9. Nunca invente companhia, preco, link ou fonte. Na duvida, omita o "
    "item — um array menor e correto vale mais que um array cheio de numeros "
    "chutados.\n"
    "10. ESCALA DOS NUMEROS (critico): use sempre o VALOR INTEIRO em reais, "
    "nunca em milhares. Ex.: uma passagem de R$ 1.900 e 1900.00, JAMAIS 1.9. "
    "Nenhuma passagem real custa menos de R$ 50. Milhas sao a quantidade TOTAL "
    "(ex.: 35000), nunca em milhares abreviados (35). Premio em milhas e sempre "
    "na casa dos milhares. Itens com numeros fora dessa escala serao "
    "descartados — confira a ordem de grandeza antes de responder.\n\n"
    "Responda SOMENTE com um array JSON (sem markdown, sem cercas ```, sem "
    "texto fora do JSON), onde cada item segue exatamente este formato:\n"
    '[{"companhia": "LATAM Airlines", "origem": "BEL", "destino": "MCO", '
    '"data_ida": "YYYY-MM-DD", "data_volta": "YYYY-MM-DD ou null", '
    '"preco_total_brl": 3850.00, "preco_ida_brl": 1900.00, '
    '"preco_volta_brl": 1950.00, "duracao_total_minutos": 780, '
    '"conexoes": [{"aeroporto": "GRU", "espera_minutos": 95}], '
    '"milhas": {"programa": "Latam Pass", "quantidade": 85000, '
    '"taxas_brl": 190.00}, "categoria": "mais_barata", '
    '"link": "https://www.latam.com/...", "fonte": "google flights"}]\n'
    "Campos sem dado real: use null (preco_ida_brl, preco_volta_brl, "
    "duracao_total_minutos, milhas) ou lista vazia (conexoes). "
    "Se, depois de seguir todos os passos, voce nao achar nenhuma tarifa "
    "real e verificavel, responda com um array vazio: []."
)


class GeminiConnection(BaseModel):
    """Uma conexao do itinerario: aeroporto e tempo de espera."""

    aeroporto: str = ""
    espera_minutos: int | None = None


class GeminiMilesOffer(BaseModel):
    """Preco em milhas no programa da propria companhia."""

    programa: str = ""
    quantidade: int | None = None
    taxas_brl: float | None = None


class GeminiFlightResult(BaseModel):
    """Schema esperado de cada item retornado pelo Gemini (JSON da pesquisa)."""

    companhia: str = ""
    origem: str
    destino: str
    data_ida: str
    data_volta: str | None = None
    preco_total_brl: float | None = Field(default=None, gt=0)
    preco_ida_brl: float | None = None
    preco_volta_brl: float | None = None
    duracao_total_minutos: int | None = None
    conexoes: list[GeminiConnection] = Field(default_factory=list)
    milhas: GeminiMilesOffer | None = None
    categoria: str = ""
    link: str = ""
    fonte: str = ""
    # Compatibilidade com o formato antigo (escalas/preco_brl), caso o modelo
    # responda no schema anterior.
    escalas: int | None = None
    preco_brl: float | None = None


class GeminiSearchProviderError(RuntimeError):
    pass


class GeminiSearchProvider(BaseProvider):
    name = "gemini_web_search"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.settings = get_settings()
        self.model = model

    def is_configured(self) -> bool:
        return bool(getattr(self.settings, "gemini_api_key", None))

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date | str,
        return_date: date | str | None = None,
        currency: str = "BRL",
        adults: int = 1,
        cabin: str = "Economy",
        limit: int = 20,
        flexible_month: bool = False,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []

        o = origin.upper()
        d = destination.upper()
        dep = _date_to_day(departure_date)
        ret = _date_to_day(return_date) if return_date else None

        prompt = _build_user_prompt(o, d, dep, ret, adults=adults, cabin=cabin, flexible_month=flexible_month)

        try:
            payload = self._call_gemini(prompt)
        except GeminiSearchProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Propaga como erro do provider: o provider_manager captura e
            # registra a mensagem real no diagnostico (ex.: 429 creditos
            # esgotados), em vez de exibir um generico "nao retornou cotacoes".
            logger.warning("Falha ao consultar Gemini web search: %s", exc)
            raise GeminiSearchProviderError(str(exc)) from exc

        return self.normalize_response(
            payload,
            origin=o,
            destination=d,
            departure_date=dep,
            return_date=ret,
            currency=currency.upper(),
            limit=limit,
            flexible_month=flexible_month,
        )

    def _call_gemini(self, prompt: str) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover
            raise GeminiSearchProviderError("SDK 'google-genai' nao instalado.") from exc

        client = genai.Client(api_key=self.settings.gemini_api_key)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            # Tarefa factual (reportar precos achados, nao criar texto):
            # temperatura baixa reduz a chance do modelo "completar" dados
            # que nao confirmou na busca.
            temperature=0,
        )

        # Se o modelo principal estiver com a cota gratuita esgotada (429
        # RESOURCE_EXHAUSTED), tenta os modelos alternativos antes de desistir
        # — cada modelo tem cota diaria propria na conta gratuita.
        last_exc: Exception | None = None
        for model in [self.model, *FALLBACK_MODELS]:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                return (getattr(response, "text", None) or "").strip()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                err = str(exc)
                if any(m in err for m in ("RESOURCE_EXHAUSTED", "429", "NOT_FOUND", "404")):
                    logger.info("Modelo %s indisponivel (quota/404); tentando proximo.", model)
                    continue
                raise

        raise last_exc or GeminiSearchProviderError("Todos os modelos Gemini falharam.")

    def normalize_response(self, payload: Any, **kwargs: Any) -> list[dict[str, Any]]:
        items = _parse_json_array(payload)
        if items is None:
            return []

        results: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            try:
                flight = GeminiFlightResult.model_validate(raw)
            except ValidationError as exc:
                logger.info("Item descartado (schema invalido): %s", exc)
                continue

            total = flight.preco_total_brl or flight.preco_brl
            if not total or total <= 0:
                logger.info("Item descartado (sem preco total): %s", flight.companhia)
                continue
            # Valor implausivelmente baixo = alucinacao/escala errada da IA
            # (ex.: R$ 1,90). Descarta em vez de exibir lixo.
            if float(total) < MIN_PLAUSIBLE_PRICE_BRL:
                logger.info(
                    "Item descartado (preco implausivel R$ %.2f): %s", float(total), flight.companhia
                )
                continue

            # Busca somente ida: item com data_volta e um pacote ida+volta.
            # Quando a fonte detalha o preco da ida, aproveitamos so esse
            # trecho (as paginas de busca mostram majoritariamente pacotes —
            # descartar tudo deixava a secao de ida quase vazia). Sem o
            # detalhamento, descarta: o total seria do pacote, nao do trecho.
            data_volta = flight.data_volta
            preco_volta = flight.preco_volta_brl
            if not kwargs.get("return_date") and data_volta:
                if flight.preco_ida_brl and 0 < float(flight.preco_ida_brl) < float(total):
                    total = float(flight.preco_ida_brl)
                    data_volta = None
                    preco_volta = None
                else:
                    logger.info(
                        "Item descartado (pacote ida+volta sem detalhamento em busca somente ida): %s",
                        flight.companhia,
                    )
                    continue

            # O valor efetivamente usado pode ter mudado para o preço apenas da
            # ida. Revalida a escala depois dessa substituição.
            if float(total) < MIN_PLAUSIBLE_PRICE_BRL:
                logger.info(
                    "Item descartado (preco efetivo implausivel R$ %.2f): %s",
                    float(total),
                    flight.companhia,
                )
                continue

            if not _matches_requested_itinerary(
                flight,
                requested_origin=str(kwargs.get("origin") or ""),
                requested_destination=str(kwargs.get("destination") or ""),
                requested_departure=str(kwargs.get("departure_date") or ""),
                requested_return=str(kwargs.get("return_date") or "") or None,
                effective_return=data_volta,
                flexible_month=bool(kwargs.get("flexible_month")),
            ):
                logger.info("Item descartado (rota/data divergente): %s", flight.companhia)
                continue

            connections = [
                {"airport": c.aeroporto.upper(), "wait_minutes": c.espera_minutos}
                for c in flight.conexoes
                if c.aeroporto
            ]
            stops = len(connections) if connections else (flight.escalas or 0)

            miles_offer = None
            # Prêmio em milhas é sempre milhares — "35 milhas" é alucinação de
            # escala; ignora o trecho de milhas (mantém o item pela tarifa cash).
            if flight.milhas and flight.milhas.quantidade and int(flight.milhas.quantidade) >= MIN_PLAUSIBLE_MILES:
                miles_offer = {
                    "program": flight.milhas.programa,
                    "amount": int(flight.milhas.quantidade),
                    "taxes_brl": float(flight.milhas.taxas_brl or 0),
                }

            # Ida/volta: quando a fonte so informa um dos trechos, o outro e
            # derivado do total (total = ida + volta) para o card sempre
            # exibir os dois precos em viagens de ida e volta.
            price_outbound = float(flight.preco_ida_brl) if flight.preco_ida_brl else None
            price_return = float(preco_volta) if preco_volta else None
            is_round_trip = bool(data_volta or kwargs.get("return_date"))
            if is_round_trip:
                if price_outbound and not price_return and float(total) > price_outbound:
                    price_return = round(float(total) - price_outbound, 2)
                elif price_return and not price_outbound and float(total) > price_return:
                    price_outbound = round(float(total) - price_return, 2)

            results.append(
                {
                    "provider": self.name,
                    "source": flight.fonte or self.name,
                    "origin": flight.origem.upper() or kwargs.get("origin"),
                    "destination": flight.destino.upper() or kwargs.get("destination"),
                    "departure_date": flight.data_ida or kwargs.get("departure_date"),
                    "return_date": data_volta or kwargs.get("return_date"),
                    "airline": flight.companhia,
                    "price": float(total),
                    "price_outbound": price_outbound,
                    "price_return": price_return,
                    "currency": kwargs.get("currency", "BRL"),
                    "duration_minutes": flight.duracao_total_minutos,
                    "stops": stops,
                    "connections": connections,
                    "miles_offer": miles_offer,
                    "category": flight.categoria or None,
                    "booking_link": _validated_booking_link(flight.link),
                    "raw_payload": {
                        "gemini_web_search": True,
                        "fonte": flight.fonte,
                        "link_rejected": bool(flight.link and not _validated_booking_link(flight.link)),
                    },
                }
            )

        results.sort(key=lambda r: r["price"])
        return results[: kwargs.get("limit", 20)]


_MONTH_NAMES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "marco", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


def _month_label(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{_MONTH_NAMES_PT.get(d.month, str(d.month))} de {d.year}"


def _build_user_prompt(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    *,
    adults: int,
    cabin: str,
    flexible_month: bool = False,
) -> str:
    # Busca SOMENTE IDA (one-way): cada trecho da viagem e pesquisado em
    # separado — o preco precisa ser apenas do trecho, nunca de pacote
    # ida+volta, e data_volta deve vir sempre null.
    one_way_note = (
        "ATENCAO: esta busca e de passagem SOMENTE IDA (one-way). "
        "Pesquise e reporte apenas tarifas one-way deste trecho: "
        "'preco_total_brl' deve ser o preco SO deste trecho (nunca de pacote "
        "ida e volta) e 'data_volta' deve ser sempre null. Se a fonte so "
        "mostrar pacotes de ida e volta, abra o detalhamento da tarifa e "
        "reporte em 'preco_total_brl' o valor apenas deste trecho. "
        if not return_date
        else ""
    )

    if flexible_month:
        month_label = _month_label(departure_date)
        duration_days = None
        if return_date:
            duration_days = (date.fromisoformat(return_date) - date.fromisoformat(departure_date)).days
        trecho = f"{origin} -> {destination}, com ida em qualquer dia de {month_label}"
        if duration_days:
            trecho += f" e permanencia de aproximadamente {duration_days} dias"
        datas_note = (
            "cada uma com sua data_ida e data_volta exatas (as datas reais da "
            "oferta, nao apenas o mes). "
            if return_date
            else "cada uma com sua data_ida exata (a data real da oferta, nao apenas o mes). "
        )
        return (
            f"Pesquise passagens aereas reais e variadas para o trecho {trecho}, "
            f"{adults} passageiro(s), classe {cabin}, com preco em reais (BRL). "
            f"{one_way_note}"
            "Nao se limite a um unico dia: varie a data de ida ao longo do mes inteiro "
            f"e retorne as opcoes mais baratas encontradas, {datas_note}"
            "Siga a estrategia de busca obrigatoria do system prompt: tente varias "
            "fontes e formulacoes. Devolva ate 10 opcoes reais distintas. "
            "Retorne apenas o array JSON especificado — nada de texto fora dele."
        )

    trecho = f"{origin} -> {destination}, ida em {departure_date}"
    trip_len = None
    if return_date:
        trecho += f", volta em {return_date}"
        trip_len = (date.fromisoformat(return_date) - date.fromisoformat(departure_date)).days
    extra_datas = (
        f"A viagem tem {trip_len} dias entre ida e volta — qualquer alternativa "
        f"de datas precisa manter exatamente essa duracao (janela inteira pode "
        f"deslizar ate 2 dias). "
        if trip_len
        else ""
    )
    precos_note = (
        "precos de ida e volta separados quando a fonte mostrar; "
        if return_date
        else ""
    )
    return (
        f"Pesquise passagens aereas reais para o trecho {trecho}, "
        f"{adults} passageiro(s), classe {cabin}, com preco em reais (BRL). "
        f"{one_way_note}"
        f"{extra_datas}"
        "Siga a estrategia de busca obrigatoria do system prompt: varias "
        f"fontes e formulacoes; {precos_note}conexoes com aeroporto e tempo "
        "de espera; preco em milhas no programa de cada companhia quando "
        "existir; link sempre do site oficial da companhia aerea. Devolva "
        "ate 10 opcoes reais distintas cobrindo as categorias mais_barata, "
        "mais_rapida e equilibrada. "
        "Retorne apenas o array JSON especificado — nada de texto fora dele."
    )


def _parse_json_array(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, str):
        return None

    text = payload.strip()
    if text.startswith("```"):
        text = text.strip("`")
        # remove possivel marcador de linguagem (ex.: "json\n...")
        if "\n" in text:
            first_line, rest = text.split("\n", 1)
            if first_line.strip().lower() in {"json", ""}:
                text = rest
        text = text.strip()

    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        logger.info("Resposta do Gemini nao e JSON valido: %s", exc)
        return None

    if not isinstance(data, list):
        logger.info("Resposta do Gemini nao e um array JSON: %r", type(data))
        return None
    return data


def _date_to_day(value: date | str) -> str:
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10]


def _parse_iso_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _matches_requested_itinerary(
    flight: GeminiFlightResult,
    *,
    requested_origin: str,
    requested_destination: str,
    requested_departure: str,
    requested_return: str | None,
    effective_return: str | None,
    flexible_month: bool,
) -> bool:
    """Reject model output that does not describe the route/date requested."""
    if flight.origem.upper() != requested_origin.upper():
        return False
    if flight.destino.upper() != requested_destination.upper():
        return False

    requested_dep = _parse_iso_day(requested_departure)
    actual_dep = _parse_iso_day(flight.data_ida)
    if requested_dep is None or actual_dep is None:
        return False

    if flexible_month:
        if (actual_dep.year, actual_dep.month) != (requested_dep.year, requested_dep.month):
            return False
    elif abs((actual_dep - requested_dep).days) > 2:
        return False

    requested_ret = _parse_iso_day(requested_return)
    actual_ret = _parse_iso_day(effective_return)
    if requested_ret:
        if actual_ret is None or actual_ret <= actual_dep:
            return False
        requested_duration = (requested_ret - requested_dep).days
        actual_duration = (actual_ret - actual_dep).days
        if actual_duration != requested_duration:
            return False
        if not flexible_month and abs((actual_ret - requested_ret).days) > 2:
            return False
    elif actual_ret is not None:
        return False
    return True


def _validated_booking_link(value: str | None) -> str:
    """Return a safe official-airline HTTPS URL, or an empty string."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return ""
    if host == "localhost" or host.replace(".", "").isdigit():
        return ""
    if not any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_BOOKING_DOMAINS):
        return ""
    return text
