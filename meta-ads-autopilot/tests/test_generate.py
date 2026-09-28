import wave

from meta_autopilot.generate.assemble import build_srt, to_srt_time
from meta_autopilot.generate.script import Scene, VideoScript, check_pattern, validate_facts
from meta_autopilot.generate.tts import SilentTTS


def _script(texts, start=0.0):
    scenes = [Scene(start_sec=start + i * 3, duration_sec=3, visual="v", visual_tag="t", on_screen_text=t, narration="")
              for i, t in enumerate(texts)]
    return VideoScript(title="x", hypothesis="h", aspect_ratio="9:16", total_sec=3 * len(texts), hook_type="anxiety",
                       appeal_axis="compensation", scenes=scenes, cta="まずは無料相談", compliance_notes="")


def test_validate_facts_flags_invented_numbers():
    s = _script(["年収450万円も", "年間休日120日"])
    assert validate_facts(s, ["年収例 450万円", "年間休日120日"]) == []
    probs = validate_facts(s, ["年収例 450万円"])
    assert len(probs) == 1 and "120" in probs[0]


def test_validate_facts_token_match_not_substring():
    s = _script(["30代歓迎"])
    assert validate_facts(s, ["年収300万円〜"])  # 30 は 300 に含まれるが別の数字


def test_check_pattern_early_exposure():
    assert check_pattern(_script(["求人"]), {"early_exposure": "yes"}) == []
    late = _script(["", "求人"])
    assert check_pattern(late, {"early_exposure": "yes"})


def test_srt():
    assert to_srt_time(61.5) == "00:01:01,500"
    srt = build_srt(_script(["A", "", "C"]), [3, 3, 3])
    assert "00:00:06,000 --> 00:00:09,000\nC" in srt and srt.count("-->") == 2


def test_silent_tts(tmp_path):
    p = tmp_path / "a.wav"
    d = SilentTTS().synthesize("あいうえおかきくけこ", p)
    with wave.open(str(p)) as w:
        assert abs(w.getnframes() / w.getframerate() - d) < 0.01
