from datetime import date

import pytest

from meta_autopilot.creative.analyzer import aspect_ratio_label, cuts_per_10s
from meta_autopilot.creative.frames import sample_times
from meta_autopilot.ingest.meta_insights import extract_conversion, refetch_window, to_bq_row
from meta_autopilot.models import Alert, Severity
from meta_autopilot.notify.slack import format_alerts

ROW = {
    "date_start": "2026-09-27", "account_id": "1", "campaign_id": "c", "adset_id": "s", "ad_id": "a",
    "spend": "1234", "impressions": "1000", "inline_link_clicks": "12",
    "actions": [{"action_type": "landing_page_view", "value": "9"},
                {"action_type": "offsite_conversion.fb_pixel_complete_registration", "value": "2"}],
    "conversions": [{"action_type": "offsite_conversion.fb_pixel_custom.Mechanic_Lead", "value": "1"}],
}


def test_to_bq_row_primary_conversion():
    r = to_bq_row(ROW, primary_conversion="actions:offsite_conversion.fb_pixel_complete_registration", fetched_at="t")
    assert (r["spend"], r["landing_page_views"], r["cv"], r["link_clicks"]) == (1234.0, 9.0, 2.0, 12)
    assert extract_conversion(ROW, "conversions:offsite_conversion.fb_pixel_custom.Mechanic_Lead") == 1.0


def test_bad_conversion_spec():
    with pytest.raises(ValueError):
        extract_conversion(ROW, "complete_registration")


def test_refetch_window_excludes_today():
    assert refetch_window(date(2026, 9, 28), 7) == (date(2026, 9, 21), date(2026, 9, 27))


def test_sample_times_dense_head():
    t = sample_times(30)
    assert t[:7] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0] and len(t) <= 40


def test_measured_helpers():
    assert aspect_ratio_label(1080, 1920) == "9:16" and aspect_ratio_label(None, 1) is None
    assert cuts_per_10s([1, 2, 3], 15) == 2.0


def test_slack_sorted_by_severity():
    a = [Alert("k", Severity.INFO, "s", "info", "c", []), Alert("k", Severity.CRITICAL, "s", "crit", "c", ["x"])]
    p = format_alerts(a, header="h")
    assert "crit" in p["blocks"][1]["text"]["text"]
