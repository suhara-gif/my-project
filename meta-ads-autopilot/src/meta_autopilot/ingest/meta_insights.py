"""Meta Marketing API(Insights)から広告×日の実績を取得し、BigQuery 取り込み用の行に整形する。

- level=ad, time_increment=1 で取得する。キャンペーン別・配信寄り・直近7日は BigQuery のビューで作る
  (API を粒度ごとに叩き分けると数字が合わなくなるため、最小粒度だけを取り込んで上で集計する)。
- CV は遅れて計上される(アトリビューション)ので、毎回直近 refetch_days 日を取り直して上書きする。
- actions / conversions は生の JSON も保存し、後から別の CV 定義で集計し直せるようにする。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Iterator

INSIGHT_FIELDS = [
    "date_start",
    "account_id",
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "spend",
    "impressions",
    "reach",
    "frequency",
    "inline_link_clicks",
    "actions",
    "conversions",
    "video_thruplay_watched_actions",
    "video_p25_watched_actions",
    "video_p100_watched_actions",
]


class GraphAPIError(RuntimeError):
    pass


def _get(url: str, params: dict, *, retries: int = 4) -> dict:
    q = urllib.parse.urlencode(params)
    full = f"{url}?{q}" if q else url
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(full, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            # レート制限・一時エラーのみ再試行。トークン失効等は即失敗させる。
            if e.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise GraphAPIError(f"HTTP {e.code}: {body[:500]}") from None
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise AssertionError("unreachable")


def fetch_ad_daily(
    account_id: str,
    since: date,
    until: date,
    *,
    access_token: str,
    api_version: str,
) -> Iterator[dict]:
    """広告×日の Insights を1行ずつ返す(ページングを辿る)。"""
    url = f"https://graph.facebook.com/{api_version}/act_{account_id}/insights"
    params = {
        "access_token": access_token,
        "level": "ad",
        "time_increment": 1,
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        "fields": ",".join(INSIGHT_FIELDS),
        "limit": 500,
    }
    page = _get(url, params)
    while True:
        yield from page.get("data", [])
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            return
        page = _get(nxt, {})


def _action_value(items: list[dict] | None, action_type: str) -> float:
    for it in items or []:
        if it.get("action_type") == action_type:
            return float(it.get("value", 0) or 0)
    return 0.0


def extract_conversion(row: dict, spec: str) -> float:
    """"actions:xxx" / "conversions:xxx" 形式の指定で CV 数を取り出す。"""
    source, _, action_type = spec.partition(":")
    if source not in ("actions", "conversions") or not action_type:
        raise ValueError(f"CV 指定の形式が不正: {spec!r}")
    return _action_value(row.get(source), action_type)


def to_bq_row(
    row: dict,
    *,
    primary_conversion: str,
    fetched_at: str,
    conversion_overrides: dict[str, str] | None = None,
) -> dict:
    """API の1行を raw_ad_daily の1行に変換する。

    conversion_overrides に広告IDがあれば、その広告だけ別のCV定義で数える。
    採用した定義は cv_definition に残るので、定義の違う広告を混ぜて集計しないこと。
    """
    primary_conversion = (conversion_overrides or {}).get(str(row["ad_id"]), primary_conversion)
    return {
        "date": row["date_start"],
        "account_id": row["account_id"],
        "campaign_id": row["campaign_id"],
        "campaign_name": row.get("campaign_name"),
        "adset_id": row["adset_id"],
        "adset_name": row.get("adset_name"),
        "ad_id": row["ad_id"],
        "ad_name": row.get("ad_name"),
        "spend": float(row.get("spend", 0) or 0),
        "impressions": int(row.get("impressions", 0) or 0),
        "reach": int(row.get("reach", 0) or 0),
        "frequency": float(row.get("frequency", 0) or 0),
        "link_clicks": int(row.get("inline_link_clicks", 0) or 0),
        "landing_page_views": _action_value(row.get("actions"), "landing_page_view"),
        "cv": extract_conversion(row, primary_conversion),
        "cv_definition": primary_conversion,
        "video_thruplay": _action_value(row.get("video_thruplay_watched_actions"), "video_view"),
        "video_p25": _action_value(row.get("video_p25_watched_actions"), "video_view"),
        "video_p100": _action_value(row.get("video_p100_watched_actions"), "video_view"),
        "actions_json": json.dumps(row.get("actions") or [], ensure_ascii=False),
        "conversions_json": json.dumps(row.get("conversions") or [], ensure_ascii=False),
        "fetched_at": fetched_at,
    }


def refetch_window(today: date, refetch_days: int) -> tuple[date, date]:
    """当日分は未確定なので含めない。昨日から遡って refetch_days 日。"""
    until = today - timedelta(days=1)
    since = until - timedelta(days=refetch_days - 1)
    return since, until


def fetch_ad_creatives(
    ad_ids: list[str], *, access_token: str, api_version: str
) -> Iterator[dict]:
    """広告IDから creative の ID・動画ID・画像URL・本文を取る(CR解析の入力)。"""
    for i in range(0, len(ad_ids), 50):
        batch = ad_ids[i : i + 50]
        data = _get(
            f"https://graph.facebook.com/{api_version}/",
            {
                "access_token": access_token,
                "ids": ",".join(batch),
                "fields": "creative{id,name,video_id,image_url,thumbnail_url,body,title,object_story_spec,asset_feed_spec}",
            },
        )
        for ad_id, v in data.items():
            c = v.get("creative", {})
            yield {"ad_id": ad_id, **c}


def video_source_url(video_id: str, *, access_token: str, api_version: str) -> str | None:
    """動画の元ファイルURL。権限によっては返らない(その場合は Ads Manager から手動で落とす)。"""
    data = _get(f"https://graph.facebook.com/{api_version}/{video_id}", {"access_token": access_token, "fields": "source"})
    return data.get("source")


def download(url: str, out_path) -> None:
    with urllib.request.urlopen(url, timeout=300) as r, open(out_path, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
