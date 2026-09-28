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


class CreativeFeatures(BaseModel):
    media_type: Literal["video", "image"]
    duration_sec: float | None = Field(None, description="動画の長さ(秒)。静止画は null")
    hook_type: HookType = Field(description="冒頭(動画は最初の3秒、静止画は最も目立つ要素)のフックの型")
    hook_text: str = Field(description="冒頭のフックの文言(テロップ・ナレーションをそのまま)")
    appeal_axis: AppealAxis = Field(description="主たる訴求軸")
    secondary_appeal_axis: AppealAxis | None = None
    benefit: str = Field(description="視聴者が得られると示されている便益を一文で")
    offer: str | None = Field(None, description="具体的な条件・特典(例: 年収例、休日数、無料相談)。無ければ null")
    cta: str | None = Field(None, description="行動喚起の文言。無ければ null")
    subject_exposure_sec: float | None = Field(
        None, description="求人・サービス名・具体条件が最初に画面/音声に出る秒。静止画は 0"
    )
    subject_exposure_total_sec: float | None = Field(None, description="求人・サービスが映っている合計秒")
    has_person: bool
    person_type: PersonType
    format_style: FormatStyle
    aspect_ratio: Literal["9:16", "4:5", "1:1", "16:9", "other"]
    shot_framing: Framing
    cuts_per_10s: float | None = Field(None, description="10秒あたりのカット数(テンポ)。静止画は null")
    has_subtitles: bool
    has_voiceover: bool | None = Field(None, description="音声が無い入力では null")
    notes: str = Field(description="上の項目で表しきれない特徴や、判断に迷った点")
