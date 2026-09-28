from meta_autopilot.offline import detect_rows, format_text


def _row(d, ad, cv, definition="omni_complete_registration", spend=5000):
    return {"date": d, "campaign_id": "c", "campaign_name": "C", "ad_id": ad, "ad_name": ad, "spend": spend,
            "impressions": 3000, "link_clicks": 30, "lpv": 25, "cv": cv, "cv_definition": definition, "frequency": 1.2}


def test_excludes_other_definition_and_null():
    rows = [_row("2026-09-01", "a", 1), _row("2026-09-02", "a", 0),
            _row("2026-09-02", "ml", None, "mechanic_lead_unavailable_via_meta_ads_mcp"),
            _row("2026-09-02", "n", None)]
    alerts, summary = detect_rows(rows, target_cpa=5800)
    assert summary["excluded"] == ["ml", "n"]
    assert summary["last7"].cv == 1
    assert "判定から除外: ml、n" in format_text("TW", alerts, summary, target_cpa=5800)
