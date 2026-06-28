from streamlit_app import _integration_status_html, _serpapi_usage_html


def _usage(**overrides):
    value = {
        "ok": True,
        "plan_name": "Free Plan",
        "monthly_limit": 250,
        "monthly_usage": 10,
        "total_searches_left": 240,
        "extra_credits": 0,
        "last_hour_searches": 0,
        "hourly_limit": 250,
        "used_percent": 4.0,
        "remaining_percent": 96.0,
        "level": "normal",
    }
    value.update(overrides)
    return value


def test_integration_status_uses_css_grid_and_escapes_labels():
    html = _integration_status_html(
        [
            ("SerpApi", True),
            ("<script>alert(1)</script>", False),
        ]
    )

    assert 'class="settings-status-grid"' in html
    assert 'class="settings-status-item is-ok"' in html
    assert 'class="settings-status-item is-off"' in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_serpapi_usage_renders_metrics_progress_and_plan_safely():
    html = _serpapi_usage_html(
        _usage(plan_name="<b>Free</b>", used_percent=40.0, remaining_percent=60.0)
    )

    assert 'class="serpapi-quota-panel level-normal"' in html
    assert "Usadas neste mês" in html
    assert "Saldo disponível" in html
    assert "width:40.0%" in html
    assert 'aria-valuenow="40.0"' in html
    assert "<b>Free</b>" not in html
    assert "&lt;b&gt;Free&lt;/b&gt;" in html


def test_serpapi_warning_and_error_states_use_css_alerts():
    warning_html = _serpapi_usage_html(
        _usage(level="warning", remaining_percent=20.0)
    )
    error_html = _serpapi_usage_html(
        {
            "ok": False,
            "message": "<script>secret</script>",
        }
    )

    assert 'class="serpapi-quota-alert warning"' in warning_html
    assert "Restam 20.0%" in warning_html
    assert 'class="serpapi-quota-panel level-error"' in error_html
    assert "<script>" not in error_html
    assert "&lt;script&gt;" in error_html
