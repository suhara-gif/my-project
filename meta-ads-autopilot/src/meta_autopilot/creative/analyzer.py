"""CR をマルチモーダル解析して CreativeFeatures に構造化する(Claude API)。

入力: 動画ならフレーム画像(タイムスタンプ付き)+ 任意の文字起こし、静止画なら画像1枚 + 広告本文。
測れるもの(長さ・テンポ)は ffprobe/ffmpeg の実測値で上書きし、LLM には「見て判断するもの」だけを任せる。

音声について: Claude API は音声を直接受け取らない。ナレーションを解析に使うなら、別の文字起こし
(STT)結果を transcript に渡す。STT を何にするかは未決定([要確認])。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from .schema import CreativeFeatures

ANALYZER_VERSION = "2026-09-28.1"

SYSTEM = """あなたは求人広告(自動車整備士向け)のクリエイティブ分析者です。
渡されたフレーム画像(各画像の直前に秒数を示します)・文字起こし・広告本文から、指定のスキーマで特徴量を返します。

- 画面・音声に実際にあるものだけを根拠にする。推測で埋めた項目は notes にその旨を書く。
- hook_type は冒頭3秒(静止画は最も目立つ要素)だけで判定する。
- subject_exposure_sec は「求人・サービス名・具体的な条件(年収・休日等)」が初めて出た秒。
- 語彙に当てはまらないものは other にして、notes に具体的に書く。"""


@dataclass
class AnalyzerInput:
    creative_id: str
    media_type: str  # video / image
    frames: list[tuple[float, Path]]  # 静止画は [(0.0, path)]
    ad_text: str = ""
    transcript: str | None = None
    measured_duration: float | None = None
    measured_cut_times: list[float] | None = None
    aspect_ratio_hint: str | None = None


def _img_block(path: Path) -> dict:
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media, "data": base64.standard_b64encode(path.read_bytes()).decode()},
    }


def build_content(inp: AnalyzerInput) -> list[dict]:
    content: list[dict] = []
    for t, p in inp.frames:
        content.append({"type": "text", "text": f"[{t:.1f}秒]"})
        content.append(_img_block(p))
    meta = [f"media_type: {inp.media_type}"]
    if inp.measured_duration is not None:
        meta.append(f"実測の長さ: {inp.measured_duration:.1f}秒")
    if inp.aspect_ratio_hint:
        meta.append(f"実測のアスペクト比: {inp.aspect_ratio_hint}")
    meta.append(f"広告本文:\n{inp.ad_text or '(なし)'}")
    meta.append(f"文字起こし:\n{inp.transcript}" if inp.transcript else "文字起こし: なし(has_voiceover は null にする)")
    content.append({"type": "text", "text": "\n\n".join(meta)})
    return content


def cuts_per_10s(cut_times: list[float], duration: float) -> float | None:
    if not duration:
        return None
    return round(len(cut_times) / duration * 10, 2)


def aspect_ratio_label(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    r = width / height
    for label, v in (("9:16", 9 / 16), ("4:5", 4 / 5), ("1:1", 1.0), ("16:9", 16 / 9)):
        if abs(r - v) < 0.03:
            return label
    return "other"


class RefusedError(RuntimeError):
    pass


def analyze(inp: AnalyzerInput, *, model: str, effort: str = "medium", client=None) -> CreativeFeatures:
    import anthropic

    client = client or anthropic.Anthropic()
    resp = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": build_content(inp)}],
        output_format=CreativeFeatures,
    )
    if resp.stop_reason == "refusal":
        raise RefusedError(f"{inp.creative_id}: 解析を拒否された ({resp.stop_details})")
    feats: CreativeFeatures = resp.parsed_output
    # 実測できる値は実測で上書きする
    if inp.measured_duration is not None:
        feats.duration_sec = round(inp.measured_duration, 2)
    if inp.measured_cut_times is not None and inp.measured_duration:
        feats.cuts_per_10s = cuts_per_10s(inp.measured_cut_times, inp.measured_duration)
    if inp.aspect_ratio_hint:
        feats.aspect_ratio = inp.aspect_ratio_hint  # type: ignore[assignment]
    return feats


def to_bq_row(creative_id: str, ad_id: str, account_id: str, f: CreativeFeatures, *, model: str, analyzed_at: str) -> dict:
    d = f.model_dump()
    return {
        "creative_id": creative_id,
        "ad_id": ad_id,
        "account_id": account_id,
        **{k: d[k] for k in (
            "media_type", "analysis_scope", "duration_sec", "hook_type", "hook_text", "appeal_axis",
            "secondary_appeal_axis", "benefit", "offer", "cta", "subject_exposure_sec", "subject_exposure_total_sec",
            "has_person", "person_type", "format_style", "aspect_ratio", "shot_framing", "cuts_per_10s",
            "has_subtitles", "has_voiceover", "notes",
        )},
        "features_json": f.model_dump_json(),
        "analyzer_model": model,
        "analyzer_version": ANALYZER_VERSION,
        "analyzed_at": analyzed_at,
    }


_CTA_JA = {
    "SIGN_UP": "今すぐ登録", "APPLY_NOW": "今すぐ応募", "LEARN_MORE": "詳しくはこちら",
    "CONTACT_US": "お問い合わせ", "GET_QUOTE": "見積もりを取得", "SEND_MESSAGE": "メッセージを送信",
    "SUBSCRIBE": "登録する", "DOWNLOAD": "ダウンロード",
}


def analyze_text_only(
    creative_id: str,
    *,
    media_type: str,
    ad_title: str,
    ad_body: str,
    call_to_action_type: str | None,
    duration_sec: float | None,
    appeal_axis,
    benefit: str | None,
    offer: str | None,
    notes: str,
) -> CreativeFeatures:
    """視覚データに到達できないときの代替解析。

    appeal_axis・benefit・offer は呼び出し側(人間またはこの関数を呼ぶ側のClaude自身)が
    広告本文・タイトルを読んで判断した値を渡す — この関数自体は分類ロジックを持たない
    (誤って自動分類が機能しているように見せないため)。cta だけは Meta の call_to_action_type
    という構造化フィールドから確定的に埋める(推測ではない)。
    """
    return CreativeFeatures(
        media_type=media_type,  # type: ignore[arg-type]
        analysis_scope="text_only",
        duration_sec=duration_sec,
        appeal_axis=appeal_axis,
        benefit=benefit or (ad_body[:120] if ad_body else None),
        offer=offer,
        cta=_CTA_JA.get(call_to_action_type or "", call_to_action_type),
        notes=notes,
    )
