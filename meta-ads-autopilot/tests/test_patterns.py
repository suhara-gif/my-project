from meta_autopilot.patterns.mine import mine_patterns


def _ad(i, camp, cv, hook, axis, spend=50_000):
    return {"ad_id": f"a{i}", "campaign_id": camp, "spend": spend, "cv": cv, "impressions": 20_000,
            "link_clicks": 200, "hook_type": hook, "appeal_axis": axis, "format_style": "ugc",
            "subject_exposure_sec": 1.0, "cuts_per_10s": 3.0}


def test_finds_planted_pattern_and_prunes_redundant():
    rows = [_ad(i, "c1", 12, "anxiety", "compensation") for i in range(4)]
    rows += [_ad(10 + i, "c1", 2, "number", "brand") for i in range(8)]
    stats = mine_patterns(rows, attributes=("hook_type", "appeal_axis", "format_style"), max_order=2)
    labels = [s.label() for s in stats]
    assert "hook_type=anxiety" in labels
    # hook と axis が完全に同じ広告集合なので、2次の組み合わせは冗長として落ちる
    assert not any("×" in l and "anxiety" in l for l in labels)


def test_campaign_level_normalization():
    # c2 は全体的に CPA が良いだけ。c2 に多い属性を「勝ち」と誤認しない
    rows = [_ad(i, "c1", 3, "number", "brand") for i in range(5)]
    rows += [_ad(10 + i, "c2", 12, "empathy", "brand") for i in range(5)]
    stats = mine_patterns(rows, attributes=("hook_type",), max_order=1)
    assert stats == []


def test_min_support():
    rows = [_ad(1, "c1", 30, "anxiety", "x"), _ad(2, "c1", 1, "number", "x"), _ad(3, "c1", 1, "number", "x")]
    assert all(s.n_ads >= 3 for s in mine_patterns(rows, attributes=("hook_type",), max_order=1))


def test_text_only_rows_excluded_from_visual_attributes():
    from meta_autopilot.patterns.mine import mine_patterns

    multimodal = [dict(_ad(i, "c1", 12, "anxiety", "compensation"), analysis_scope="multimodal") for i in range(4)]
    multimodal += [dict(_ad(100 + i, "c1", 2, "number", "brand"), analysis_scope="multimodal") for i in range(8)]
    text_only_dup = [dict(_ad(200 + i, "c1", 12, "anxiety", "compensation"), analysis_scope="text_only") for i in range(4)]
    stats_mixed = mine_patterns(multimodal + text_only_dup, attributes=("hook_type",), max_order=1)
    stats_multimodal_only = mine_patterns(multimodal, attributes=("hook_type",), max_order=1)
    # text_only 行が混ざっていても、視覚属性(hook_type)の判定は multimodal 12件だけから出た結果と同じになる
    assert [s.n_ads for s in stats_mixed] == [s.n_ads for s in stats_multimodal_only] == [4]


def test_text_only_rows_kept_for_non_visual_attributes():
    from meta_autopilot.patterns.mine import mine_patterns

    high = [dict(_ad(i, "c1", 12, "anxiety", "compensation"), analysis_scope="text_only") for i in range(4)]
    low = [dict(_ad(10 + i, "c1", 2, "number", "brand"), analysis_scope="text_only") for i in range(8)]
    stats = mine_patterns(high + low, attributes=("appeal_axis",), max_order=1)
    assert stats and stats[0].n_ads == 4  # appeal_axis はテキストからでも埋めてよい項目なので除外しない
