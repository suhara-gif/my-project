"""CR 解析結果の構造。creative_features テーブルと1対1で対応させる。

カテゴリ値は語彙を固定する(自由記述だと「待遇訴求」「給与訴求」「年収訴求」が別物として
集計され、パターン分析のサンプルが割れて何も言えなくなるため)。語彙に無いものは other に寄せ、
詳細は *_text / notes に残す。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

HookType = Literal[
    "question",  # 問いかけ
    "number",  # 数字(年収・休日数など)
    "pain",  # 悩み・不満の代弁
    "anxiety",  # 不安訴求(将来・体力・待遇)
    "empathy",  # 共感・あるある
    "surprise",  # 意外性
    "authority",  # 実績・権威
    "testimonial",  # 本人の声・UGC風
    "direct_offer",  # いきなり条件提示
    "other",
]

AppealAxis = Literal[
    "compensation",  # 給与・年収・待遇
    "work_environment",  # 休日・残業・設備・人間関係
    "anxiety_relief",  # 不安の解消
    "career",  # キャリア・資格・成長
    "location",  # 地域・通勤
    "ease_of_applying",  # 応募・相談の手軽さ
    "agent_support",  # エージェントのサポート
    "brand",  # 媒体・企業ブランド
    "other",
]

FormatStyle = Literal["ugc", "interview", "text_overlay", "explainer", "slideshow", "live_action_drama", "static_banner", "other"]
Framing = Literal["selfie", "close_up", "medium", "wide", "hands_work", "screen_text_only", "mixed"]
PersonType = Literal["mechanic_like", "recruiter", "narrator_only", "customer", "none", "other"]


AnalysisScope = Literal["multimodal", "text_only"]
# multimodal: フレーム画像/静止画を実際に見て判定した(このスキーマが本来想定する解析)。
# text_only : 画素データに到達できず(ネットワークポリシー等)、広告本文・タイトル・CTA等の
#             構造化フィールドだけから埋めた。視覚依存の項目は None のまま残る。
# パターン分析(patterns/mine.py)は analysis_scope を見て、visual 系の項目を含む分析では
# text_only 行を除外すること(混ぜると「見た目の特徴」の統計が実際には未観測データで汚染される)。


class CreativeFeatures(BaseModel):
    media_type: Literal["video", "image"]
    analysis_scope: AnalysisScope = Field(
        "multimodal", description="この解析がどこまで見て判定したか。text_only は視覚項目が未観測"
    )
    duration_sec: float | None = Field(None, description="動画の長さ(秒)。静止画は null")
    # 以下は視覚(または音声)を実際に見ないと判定できない項目。text_only 解析では None のまま残す
    # (推測で埋めない — 埋めるとパターン分析が未観測データに基づいて誤った結論を出す)。
    hook_type: HookType | None = Field(None, description="冒頭(動画は最初の3秒、静止画は最も目立つ要素)のフックの型")
    hook_text: str | None = Field(None, description="冒頭のフックの文言(テロップ・ナレーションをそのまま)")
    subject_exposure_sec: float | None = Field(
        None, description="求人・サービス名・具体条件が最初に画面/音声に出る秒。静止画は 0"
    )
    subject_exposure_total_sec: float | None = Field(None, description="求人・サービスが映っている合計秒")
    has_person: bool | None = None
    person_type: PersonType | None = None
    format_style: FormatStyle | None = None
    aspect_ratio: Literal["9:16", "4:5", "1:1", "16:9", "other"] | None = None
    shot_framing: Framing | None = None
    cuts_per_10s: float | None = Field(None, description="10秒あたりのカット数(テンポ)。静止画は null")
    has_subtitles: bool | None = None
    has_voiceover: bool | None = Field(None, description="音声が無い入力/未確認では null")
    # 以下は広告のテキスト情報(本文・タイトル・CTAボタン種別)だけからでも、text_only で埋めてよい項目。
    # ただし出典はあくまで「広告文が主張していること」で、動画冒頭に実際に出る演出とは限らない
    # (例: 本文に書かれた条件が動画の10秒目で初めて出る、等はここからは分からない)。
    appeal_axis: AppealAxis | None = Field(None, description="主たる訴求軸。本文・タイトルの文言から読み取れる範囲で可")
    secondary_appeal_axis: AppealAxis | None = None
    benefit: str | None = Field(None, description="視聴者が得られると示されている便益を一文で。本文から引用可")
    offer: str | None = Field(None, description="具体的な条件・特典(例: 年収例、休日数、無料相談)。無ければ null")
    cta: str | None = Field(None, description="行動喚起の文言。Metaのcall_to_action_typeから確定的に埋めてよい")
    notes: str = Field(description="上の項目で表しきれない特徴や、判断に迷った点。text_only では未取得の理由も書く")
