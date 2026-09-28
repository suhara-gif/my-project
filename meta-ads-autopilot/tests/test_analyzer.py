from types import SimpleNamespace

from meta_autopilot.creative.analyzer import AnalyzerInput, analyze, build_content, to_bq_row
from meta_autopilot.creative.schema import CreativeFeatures

FEATS = dict(media_type="video", duration_sec=99, hook_type="anxiety", hook_text="このままで大丈夫?",
             appeal_axis="compensation", benefit="年収が上がる", has_person=True, person_type="mechanic_like",
             format_style="ugc", aspect_ratio="1:1", shot_framing="selfie", cuts_per_10s=9,
             has_subtitles=True, notes="")


class FakeMessages:
    def __init__(self):
        self.kwargs = None

    def parse(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, parsed_output=CreativeFeatures(**FEATS))


def test_measured_values_override_llm(tmp_path):
    img = tmp_path / "f.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    fake = SimpleNamespace(messages=FakeMessages())
    inp = AnalyzerInput("cr1", "video", [(0.0, img)], measured_duration=20.0,
                        measured_cut_times=[1, 2, 3, 4], aspect_ratio_hint="9:16")
    f = analyze(inp, model="claude-opus-5-5", client=fake)
    assert (f.duration_sec, f.cuts_per_10s, f.aspect_ratio) == (20.0, 2.0, "9:16")
    assert fake.messages.kwargs["output_format"] is CreativeFeatures
    row = to_bq_row("cr1", "ad1", "acc", f, model="m", analyzed_at="t")
    assert row["hook_type"] == "anxiety" and '"hook_text"' in row["features_json"]


def test_content_marks_missing_transcript(tmp_path):
    img = tmp_path / "f.png"
    img.write_bytes(b"\x89PNG")
    c = build_content(AnalyzerInput("cr1", "image", [(0.0, img)]))
    assert c[1]["source"]["media_type"] == "image/png"
    assert "has_voiceover は null" in c[-1]["text"]


def test_text_only_analysis_leaves_visual_fields_none():
    from meta_autopilot.creative.analyzer import analyze_text_only

    f = analyze_text_only(
        "cr9", media_type="video", ad_title="t", ad_body="年間休日120日以上・年収500万円以上の求人多数",
        call_to_action_type="SIGN_UP", duration_sec=19.32, appeal_axis="compensation",
        benefit="年間休日120日以上・年収500万円以上の求人多数", offer="年収500万円以上", notes="fbcdn.net遮断のため画素未取得",
    )
    assert f.analysis_scope == "text_only"
    assert f.cta == "今すぐ登録" and f.duration_sec == 19.32
    assert f.hook_type is None and f.has_person is None and f.format_style is None


def test_to_bq_row_includes_analysis_scope():
    from meta_autopilot.creative.analyzer import analyze_text_only, to_bq_row

    f = analyze_text_only("cr9", media_type="image", ad_title="t", ad_body="b", call_to_action_type=None,
                          duration_sec=None, appeal_axis=None, benefit=None, offer=None, notes="n")
    row = to_bq_row("cr9", "ad9", "acc", f, model="manual", analyzed_at="t")
    assert row["analysis_scope"] == "text_only" and row["hook_type"] is None
