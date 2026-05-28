from datetime import datetime, timezone

import pandas as pd

from streamlit_app import safe_datetime_series


def test_safe_datetime_series_handles_mixed_timezones_and_bad_values():
    values = pd.Series(
        [
            datetime(2026, 5, 28, 10, 0),
            datetime(2026, 5, 28, 11, 0, tzinfo=timezone.utc),
            "2026-05-28 12:00:00+00:00",
            "valor invalido",
        ]
    )

    parsed = safe_datetime_series(values)

    assert parsed.notna().sum() == 3
    assert str(parsed.dtype) == "datetime64[ns, UTC]"
