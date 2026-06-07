from types import SimpleNamespace

import pytest

import price_alert_bot


class _FakeModels:
    def __init__(self, text: str):
        self._text = text
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=self._text)


class _FakeClient:
    captured: list["_FakeClient"] = []

    def __init__(self, text: str = "Caiu o preco para sua rota favorita! Aproveite agora. ✈️"):
        self.models = _FakeModels(text)
        _FakeClient.captured.append(self)


def _patch_client(monkeypatch, text: str | None = None):
    _FakeClient.captured = []

    def _factory():
        return _FakeClient(text) if text is not None else _FakeClient()

    monkeypatch.setattr(price_alert_bot.genai, "Client", _factory)
    return _FakeClient


def test_write_alert_returns_nonempty_string(monkeypatch):
    fake_cls = _patch_client(monkeypatch, text="Boa noticia: a passagem para o Rio caiu 32%! 🔥")

    best = {"origin": "GRU", "destination": "GIG", "airline": "LATAM", "stops": 0, "price": 412.50}
    result = price_alert_bot.write_alert(best, old_price=610.0, drop_pct=32.4)

    assert isinstance(result, str)
    assert result.strip() != ""
    assert result == "Boa noticia: a passagem para o Rio caiu 32%! 🔥"
    assert len(fake_cls.captured) == 1


def test_write_alert_prompt_includes_new_price_and_drop_pct(monkeypatch):
    fake_cls = _patch_client(monkeypatch)

    best = {"origin": "GRU", "destination": "LIS", "airline": "TAP", "stops": 1, "price": 2789.90}
    price_alert_bot.write_alert(best, old_price=3500.0, drop_pct=20.3)

    client = fake_cls.captured[0]
    assert len(client.models.calls) == 1
    sent_prompt = client.models.calls[0]["contents"]

    assert "2789.90" in sent_prompt
    assert "20.3" in sent_prompt
    assert client.models.calls[0]["model"] == price_alert_bot.GEMINI_MODEL
