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
