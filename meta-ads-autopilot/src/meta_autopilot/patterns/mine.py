"""CR 特徴量 × 実績から「勝ちパターン候補」を探す。

注意(出力を読む人向け):
- これは観察データ。Meta は成績の良さそうなCRに配信を寄せるので、「配信が多く回ったCRの特徴」と
  「成果を生む特徴」が混ざる。出力は**検証すべき仮説**であり、勝ちパターンの確定ではない。
  確定させるのは lifecycle(新CRを既存勝ちCRと並走させた比較)の役目。
- 組み合わせを大量に試すと偶然の当たりが出る。確率の閾値を高めにし、support の下限を設ける。

手法: キャンペーンごとの平均CV効率で期待CVを出し(間接標準化)、属性の組み合わせに当てはまる
広告群の「実CV ÷ 期待CV」を Gamma 事前分布で 1 に縮約して lift とする。アカウント・キャンペーン間の
CPA 水準差(TW と CW で CPA が違う等)を打ち消すため、生の CPA では比べない。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

DEFAULT_ATTRIBUTES = (
    "hook_type",
    "appeal_axis",
    "format_style",
    "person_type",
    "shot_framing",
    "aspect_ratio",
    "early_exposure",  # 派生: subject_exposure_sec <= 2
    "tempo",  # 派生: cuts_per_10s の3分位
)


@dataclass(frozen=True)
class PatternStat:
    conditions: tuple[tuple[str, str], ...]
    n_ads: int
    n_campaigns: int
    spend: float
    cv_observed: float
    cv_expected: float
    lift_mean: float
    prob_lift_gt_1: float
    ctr_lift: float  # CV が少ない段階での早期シグナル
    ad_ids: list[str] = field(default_factory=list, compare=False)

    def label(self) -> str:
        return " × ".join(f"{k}={v}" for k, v in self.conditions)


def _derive(row: dict, tempo_cuts: tuple[float, float] | None) -> dict:
    r = dict(row)
    exp = r.get("subject_exposure_sec")
    r["early_exposure"] = "yes" if exp is not None and exp <= 2 else "no" if exp is not None else None
    c = r.get("cuts_per_10s")
    if c is None or tempo_cuts is None:
        r["tempo"] = None
    else:
        r["tempo"] = "slow" if c <= tempo_cuts[0] else "fast" if c > tempo_cuts[1] else "mid"
    return r


def mine_patterns(
    rows: list[dict],
    *,
    attributes: tuple[str, ...] = DEFAULT_ATTRIBUTES,
    max_order: int = 3,
    min_ads: int = 3,
    min_expected_cv: float = 3.0,
    prior_strength: float = 3.0,
    min_prob: float = 0.95,
    draws: int = 20_000,
    seed: int = 0,
) -> list[PatternStat]:
    """rows は v_creative_performance の行(campaign_id, ad_id, spend, cv, impressions, link_clicks, 特徴量)。

    attributes に視覚依存の項目(hook_type/format_style/person_type/shot_framing/aspect_ratio/
    early_exposure/tempo)が1つでも含まれる場合、analysis_scope='text_only' の行(画素を見ずに
    本文だけで埋めた行。視覚系の値は全てNULL)は自動的に除外する。含めると「見ていないのに
    見た目の特徴で勝った」という誤った結論になるため。
    """
    rows = [r for r in rows if (r.get("spend") or 0) > 0]
    visual_attrs = {"hook_type", "format_style", "person_type", "shot_framing", "aspect_ratio", "early_exposure", "tempo"}
    if visual_attrs & set(attributes):
        rows = [r for r in rows if r.get("analysis_scope", "multimodal") == "multimodal"]
    if not rows:
        return []
    cuts = [r["cuts_per_10s"] for r in rows if r.get("cuts_per_10s") is not None]
    tempo_cuts = tuple(np.quantile(cuts, [1 / 3, 2 / 3])) if len(cuts) >= 6 else None
    rows = [_derive(r, tempo_cuts) for r in rows]

    # キャンペーンの平均効率(CV/円, クリック/imp)で期待値を出す
    camp: dict[str, dict[str, float]] = {}
    for r in rows:
        c = camp.setdefault(r["campaign_id"], {"spend": 0.0, "cv": 0.0, "imp": 0.0, "clk": 0.0})
        c["spend"] += r["spend"]
        c["cv"] += r.get("cv") or 0
        c["imp"] += r.get("impressions") or 0
        c["clk"] += r.get("link_clicks") or 0
    for r in rows:
        c = camp[r["campaign_id"]]
        r["_exp_cv"] = r["spend"] * (c["cv"] / c["spend"]) if c["spend"] else 0.0
        r["_exp_clk"] = (r.get("impressions") or 0) * (c["clk"] / c["imp"]) if c["imp"] else 0.0

    rng = np.random.default_rng(seed)
    results: list[PatternStat] = []
    for order in range(1, max_order + 1):
        for attrs in itertools.combinations(attributes, order):
            groups: dict[tuple, list[dict]] = {}
            for r in rows:
                key = tuple(r.get(a) for a in attrs)
                if any(v is None for v in key):
                    continue
                groups.setdefault(key, []).append(r)
            for key, members in groups.items():
                if len(members) < min_ads:
                    continue
                obs = sum(m.get("cv") or 0 for m in members)
                exp = sum(m["_exp_cv"] for m in members)
                if exp < min_expected_cv:
                    continue
                # lift ~ Gamma(k + obs, k + exp): 事前は lift=1 を中心に k 件ぶんの重み
                samples = rng.gamma(prior_strength + obs, 1.0 / (prior_strength + exp), draws)
                p = float(np.mean(samples > 1))
                if p < min_prob:
                    continue
                clk_obs = sum(m.get("link_clicks") or 0 for m in members)
                clk_exp = sum(m["_exp_clk"] for m in members)
                results.append(
                    PatternStat(
                        conditions=tuple(zip(attrs, [str(k) for k in key])),
                        n_ads=len(members),
                        n_campaigns=len({m["campaign_id"] for m in members}),
                        spend=float(sum(m["spend"] for m in members)),
                        cv_observed=float(obs),
                        cv_expected=float(exp),
                        lift_mean=float((prior_strength + obs) / (prior_strength + exp)),
                        prob_lift_gt_1=p,
                        ctr_lift=float(clk_obs / clk_exp) if clk_exp else float("nan"),
                        ad_ids=[m["ad_id"] for m in members],
                    )
                )
    return prune_redundant(results)


def prune_redundant(stats: list[PatternStat]) -> list[PatternStat]:
    """上位パターン(条件が少ない方)と同じ広告集合で lift もほぼ同じなら、条件の多い方を捨てる。
    「A×B が勝ち」と言っても実は A だけで説明できる、という水増しを防ぐ。"""
    stats = sorted(stats, key=lambda s: (len(s.conditions), -s.lift_mean))
    kept: list[PatternStat] = []
    for s in stats:
        cond = set(s.conditions)
        redundant = any(
            set(k.conditions) < cond and set(k.ad_ids) == set(s.ad_ids) for k in kept
        )
        if not redundant:
            kept.append(s)
    return sorted(kept, key=lambda s: (-s.prob_lift_gt_1, -s.lift_mean))
