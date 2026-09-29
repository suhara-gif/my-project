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


def test_judge_new_crs_uses_same_days_and_campaign_rest():
    from meta_autopilot.offline import judge_new_crs

    rows = []
    for i in range(30):
        d = f"2026-09-{i + 1:02d}" if i < 30 else ""
        rows.append(_row(d, "old", 1 if i % 4 == 0 else 0))
    # 新CR: 最後の6日だけ配信、費用は目標CPA×2 以上、CVなし
    for i in range(24, 30):
        rows.append(_row(f"2026-09-{i + 1:02d}", "new", 0, spend=5000))
    res = judge_new_crs(rows, target_cpa=5800)
    assert [r.ad_id for r in res] == ["new"]
    assert res[0].evidence["days"] == 6 and res[0].evidence["control_ads"] == 1
    # 既存(old)は新CR扱いにならない
    assert all(r.ad_id != "old" for r in res)
