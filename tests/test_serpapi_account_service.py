from types import SimpleNamespace

import pytest
import requests

import services.serpapi_account_service as account_service


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _settings(api_key="secret-serpapi-key"):
    return SimpleNamespace(serpapi_api_key=api_key)


def test_fetch_usage_returns_only_sanitized_quota_fields(monkeypatch):
    payload = {
        "account_id": "private-account-id",
        "api_key": "secret-serpapi-key",
        "account_email": "private@example.com",
        "plan_name": "Free",
        "searches_per_month": 250,
        "this_month_usage": 100,
        "plan_searches_left": 150,
        "total_searches_left": 160,
        "extra_credits": 10,
        "last_hour_searches": 4,
        "account_rate_limit_per_hour": 50,
    }
    monkeypatch.setattr(
        account_service.requests,
        "get",
        lambda *args, **kwargs: _Response(payload),
    )

    result = account_service.fetch_serpapi_usage(_settings())

    assert result["ok"] is True
    assert result["monthly_limit"] == 250
    assert result["monthly_usage"] == 100
    assert result["total_searches_left"] == 160
    assert result["used_percent"] == 40.0
    assert result["remaining_percent"] == 64.0
    serialized = repr(result)
    assert "secret-serpapi-key" not in serialized
    assert "private@example.com" not in serialized
    assert "private-account-id" not in serialized


@pytest.mark.parametrize(
    ("left", "expected_level"),
    [
        (100, "normal"),
        (25, "warning"),
        (10, "critical"),
        (0, "exhausted"),
    ],
)
def test_usage_level_tracks_remaining_quota(monkeypatch, left, expected_level):
    monkeypatch.setattr(
        account_service.requests,
        "get",
        lambda *args, **kwargs: _Response(
            {
                "searches_per_month": 100,
                "this_month_usage": 100 - left,
                "plan_searches_left": left,
                "total_searches_left": left,
            }
        ),
    )

    result = account_service.fetch_serpapi_usage(_settings())

    assert result["level"] == expected_level


def test_missing_key_does_not_call_account_api(monkeypatch):
    def _unexpected_call(*args, **kwargs):
        raise AssertionError("Account API should not be called")

    monkeypatch.setattr(account_service.requests, "get", _unexpected_call)

    result = account_service.fetch_serpapi_usage(_settings(api_key=None))

    assert result["status"] == "not_configured"


def test_network_and_invalid_key_errors_do_not_expose_secret(monkeypatch):
    secret = "never-show-this-key"

    def _network_error(*args, **kwargs):
        raise requests.RequestException("request failed")

    monkeypatch.setattr(account_service.requests, "get", _network_error)
    network_result = account_service.fetch_serpapi_usage(_settings(secret))
    assert network_result["ok"] is False
    assert secret not in repr(network_result)

    monkeypatch.setattr(
        account_service.requests,
        "get",
        lambda *args, **kwargs: _Response({}, status_code=403),
    )
    invalid_result = account_service.fetch_serpapi_usage(_settings(secret))
    assert invalid_result["status"] == "invalid_key"
    assert secret not in repr(invalid_result)
