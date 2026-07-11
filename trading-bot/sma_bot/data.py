"""株価データの取得と読み書き。

- CSV (Date,Open,High,Low,Close,Volume) の読み書き
- Alpaca Market Data API からの日足取得 (APIキーが必要)

このリポジトリの data/sample/ に入っている CSV は gen_sample_data.py が生成した
【合成データ】であり、実在銘柄の実際の価格ではない。動作確認・学習専用。
"""

from __future__ import annotations

import csv
import json
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

from .config import DATA_BASE_URL, api_credentials
from .strategy import Bar


def load_csv(path: str | Path) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bars.append(
                Bar(
                    day=date.fromisoformat(row["Date"]),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(float(row.get("Volume") or 0)),
                )
            )
    bars.sort(key=lambda b: b.day)
    return bars


def save_csv(path: str | Path, bars: list[Bar]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
        for b in bars:
            writer.writerow([b.day.isoformat(), f"{b.open:.4f}", f"{b.high:.4f}", f"{b.low:.4f}", f"{b.close:.4f}", b.volume])


def fetch_alpaca_daily_bars(symbol: str, start: date, end: date, feed: str = "iex") -> list[Bar]:
    """Alpaca Market Data API v2 から日足を取得する。

    無料プランでは feed="iex" を使う (SIP は有料)。ページネーション対応。
    """
    key, secret = api_credentials()
    bars: list[Bar] = []
    page_token: str | None = None
    while True:
        params = {
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": "10000",
            "adjustment": "split",
            "feed": feed,
        }
        if page_token:
            params["page_token"] = page_token
        url = f"{DATA_BASE_URL}/v2/stocks/{urllib.parse.quote(symbol)}/bars?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        for raw in payload.get("bars") or []:
            day = datetime.fromisoformat(raw["t"].replace("Z", "+00:00")).date()
            bars.append(Bar(day=day, open=raw["o"], high=raw["h"], low=raw["l"], close=raw["c"], volume=int(raw["v"])))
        page_token = payload.get("next_page_token")
        if not page_token:
            break
    bars.sort(key=lambda b: b.day)
    return bars
