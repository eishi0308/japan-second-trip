"""Open-Meteo serves daily model output; the monthly normal is derived here."""

from __future__ import annotations

from jst_api.providers.weather import monthly_normals


def test_days_are_averaged_into_their_calendar_month() -> None:
    daily = {
        "time": ["2011-10-01", "2011-10-02", "2012-10-01", "2011-01-15"],
        "temperature_2m_max": [20.0, 22.0, 18.0, 4.0],
        "temperature_2m_min": [12.0, 14.0, 10.0, -3.0],
    }
    normals = monthly_normals(daily)
    assert normals[10] == (20.0, 12.0)
    assert normals[1] == (4.0, -3.0)


def test_missing_readings_are_skipped_rather_than_counted_as_zero() -> None:
    daily = {
        "time": ["2011-07-01", "2011-07-02"],
        "temperature_2m_max": [30.0, None],
        "temperature_2m_min": [22.0, 21.0],
    }
    assert monthly_normals(daily) == {7: (30.0, 22.0)}


def test_an_empty_block_yields_no_months() -> None:
    assert monthly_normals({}) == {}
