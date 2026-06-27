from types import SimpleNamespace

import services.choice_assistant_service as assistant


def _settings(*, openai=False, gemini=False):
    return SimpleNamespace(
        openai_api_key="openai-key" if openai else None,
        gemini_api_key="gemini-key" if gemini else None,
        choice_assistant_provider="auto",
        openai_choice_model="gpt-test",
        gemini_choice_model="gemini-test",
    )


def _offer(
    price=1000.0,
    *,
    airline="LA",
    duration=120,
    stops=0,
    provider="serpapi_google_flights",
    confidence="real",
    link="https://www.google.com/travel/flights/example",
):
    return {
        "price_brl": price,
        "airline": airline,
        "duration_minutes": duration,
        "stops": stops,
        "provider": provider,
        "source": provider,
        "source_confidence": confidence,
        "booking_link": link,
        "departure_date": "2026-09-10",
    }


def _round_trip(price, *, separate=False, duration=240):
    provider = "montado: ida + volta (2 bilhetes)" if separate else "serpapi_google_flights"
    option = _offer(
        price=price,
        duration=duration,
        provider=provider,
        link="https://www.google.com/travel/flights/round-trip",
    )
    option.update(
        {
            "return_date": "2026-09-17",
            "source": "montado_ida_volta" if separate else "serpapi_google_flights",
            "separate_ticket": separate,
            "separate_round_trip": separate,
        }
    )
    return option


def test_local_assistant_uses_only_confirmed_linked_offers():
    confirmed = _offer(price=1200)
    unverified = _offer(
        price=100,
        provider="openai_web_search",
        confidence="unverified",
    )

    result = assistant.analyze_confirmed_offers(
        [unverified, confirmed],
        {"max_price": 1500},
        engine="local",
        settings=_settings(),
    )

    assert result["ok"] is True
    assert result["mode"] == "local"
    assert result["confirmed_count"] == 1
    assert result["selected_offer"]["price_brl"] == 1200
    assert result["selected_offer"]["booking_link"] == confirmed["booking_link"]


def test_offer_without_source_link_is_not_eligible():
    result = assistant.analyze_confirmed_offers(
        [_offer(link="")],
        {},
        settings=_settings(),
    )

    assert result["ok"] is False


def test_ai_can_only_select_existing_offer_and_valid_codes(monkeypatch):
    first = _offer(price=900, airline="G3", duration=240, stops=1)
    second = _offer(price=1050, airline="LA", duration=100, stops=0)

    def _fake_openai(prepared, *_args):
        selected_id = next(item["_offer_id"] for item in prepared if item["airline"] == "LA")
        alternative_id = next(item["_offer_id"] for item in prepared if item["airline"] == "G3")
        return (
            f'{{"selected_offer_id":"{selected_id}",'
            '"reason_codes":["FASTEST","INVENTED_PRICE"],'
            f'"warning_codes":["FAKE_WARNING"],"alternative_offer_id":"{alternative_id}"}}'
        )

    monkeypatch.setattr(assistant, "_call_openai", _fake_openai)

    result = assistant.analyze_confirmed_offers(
        [first, second],
        {},
        engine="openai",
        settings=_settings(openai=True),
    )

    assert result["mode"] == "openai"
    assert result["selected_offer"]["airline"] == "LA"
    assert result["reasons"] == [assistant.REASON_LABELS["FASTEST"]]
    assert result["warnings"] == []
    assert result["alternative_offer"]["airline"] == "G3"


def test_invalid_ai_offer_id_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(
        assistant,
        "_call_gemini",
        lambda *args: (
            '{"selected_offer_id":"F99","reason_codes":[],"warning_codes":[],'
            '"alternative_offer_id":null}'
        ),
    )

    result = assistant.analyze_confirmed_offers(
        [_offer()],
        {},
        engine="gemini",
        settings=_settings(gemini=True),
    )

    assert result["mode"] == "local"
    assert "contrato seguro" in result["fallback_reason"]


def test_llm_payload_has_no_links_airlines_or_dates():
    prepared = assistant._prepare_offers([_offer()], {})

    payload = assistant._ai_payload(prepared, {})
    serialized = str(payload)

    assert "https://" not in serialized
    assert "2026-09-10" not in serialized
    assert "'LA'" not in serialized
    assert payload["offers"][0]["offer_id"] == "F1"


def test_round_trip_verdict_compares_closed_and_separate_formats():
    closed = _round_trip(1000)
    separate = _round_trip(600, separate=True)

    result = assistant.analyze_confirmed_offers(
        [closed, separate],
        {},
        engine="local",
        settings=_settings(),
    )

    assert result["verdict_kind"] == "separate_reservations"
    assert result["selected_offer"]["price_brl"] == 600
    assert result["best_closed_offer"]["price_brl"] == 1000
    assert result["best_separate_offer"]["price_brl"] == 600
    assert assistant.WARNING_LABELS["SEPARATE_TICKETS"] in result["warnings"]


def test_closed_package_wins_when_separate_savings_are_too_small_for_the_risk():
    closed = _round_trip(1000)
    separate = _round_trip(900, separate=True)

    result = assistant.analyze_confirmed_offers(
        [closed, separate],
        {},
        engine="local",
        settings=_settings(),
    )

    assert result["verdict_kind"] == "single_booking"
    assert result["selected_offer"]["price_brl"] == 1000
    assert assistant.REASON_LABELS["SINGLE_BOOKING"] in result["reasons"]


def test_ai_context_preserves_both_booking_formats_when_one_dominates():
    closed_options = [
        _round_trip(700 + index * 10, duration=200 + index)
        for index in range(15)
    ]
    expensive_separate = _round_trip(5000, separate=True, duration=600)

    prepared = assistant._prepare_offers(
        [*closed_options, expensive_separate],
        {},
    )

    assert len(prepared) == assistant.MAX_OFFERS_FOR_AI
    assert any(item.get("separate_round_trip") for item in prepared)
    assert any(not item.get("separate_round_trip") for item in prepared)
