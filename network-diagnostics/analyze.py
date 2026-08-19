#!/usr/bin/env python3
"""net_diag.py が出力した JSON から、判断に使える指標だけを抜き出して並べる。

このスクリプトは「ボトルネックはこれだ」と断定はしない。
- 一般に公開されている閾値 (SNRやRSSIの目安など) を実測値に当てはめて分類する。
- 各指標が実測データからそのまま読める事実か、複数指標を組み合わせた推測かを
  タグ付けして出力する。最終的な結論はこの出力を見た人間 (または結果を渡された
  Claude) が書く。

使い方:
    python3 analyze.py results/xxxx_after.json
    python3 analyze.py --before results/xxxx_before.json --after results/xxxx_after.json
"""

import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fmt(v, unit="", digits=1):
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.{digits}f}{unit}"
    return f"{v}{unit}"


def classify_snr(snr):
    if snr is None:
        return "不明"
    if snr >= 40:
        return "優 (>=40dB)"
    if snr >= 25:
        return "良 (25-40dB)"
    if snr >= 15:
        return "境界 (15-25dB)"
    return "不良 (<15dB) — 一般的な目安ではWi-Fi品質劣化の域"


def classify_rssi(rssi):
    if rssi is None:
        return "不明"
    if rssi >= -50:
        return "優 (>=-50dBm)"
    if rssi >= -60:
        return "良 (-60〜-50dBm)"
    if rssi >= -70:
        return "可 (-70〜-60dBm)"
    return "不良 (<-70dBm)"


def lines_wifi(d):
    w = d.get("wifi", {})
    if w.get("error"):
        return [f"- [未検証] Wi-Fi情報取得失敗: {w['error']}"]
    out = [
        f"- [実測] RSSI={fmt(w.get('rssi_dbm'),'dBm',0)} ({classify_rssi(w.get('rssi_dbm'))})",
        f"- [実測] Noise={fmt(w.get('noise_dbm'),'dBm',0)}",
        f"- [実測] SNR={fmt(w.get('snr_db'),'dB',0)} ({classify_snr(w.get('snr_db'))})",
        f"- [実測] 規格={w.get('standard','N/A')} / チャンネル={w.get('channel','N/A')} / 帯域幅={fmt(w.get('bandwidth_mhz'),'MHz',0)}",
        f"- [実測] リンク速度={fmt(w.get('link_speed_mbps'),'Mbps',0)}",
    ]
    return out


def lines_ipv6(d):
    v = d.get("ipv6", {})
    if v.get("error"):
        return [f"- [未検証] IPv6情報取得失敗: {v['error']}"]
    has_global = v.get("has_global_address")
    has_route = v.get("has_default_route")
    out = [
        f"- [実測] グローバルIPv6アドレス: {'あり' if has_global else 'なし'} ({v.get('global_addresses')})",
        f"- [実測] IPv6デフォルト経路: {'あり' if has_route else 'なし'}",
    ]
    if not has_global or not has_route:
        out.append("- [推測] IPv6が使えていない → PPPoE接続の可能性。契約ISPのIPoE(IPv6 IPoE + IPv4 over IPv6)化に必要な条件は別途要確認 [要確認]")
    return out


def lines_latency(d):
    lat = d.get("latency", {})
    out = []
    gw = lat.get("gateway", {})
    cf = lat.get("cloudflare_1_1_1_1", {})
    gg = lat.get("google_8_8_8_8", {})
    for label, x in [("ゲートウェイ", gw), ("1.1.1.1", cf), ("8.8.8.8", gg)]:
        if x.get("error"):
            out.append(f"- [未検証] {label}: {x['error']}")
        else:
            out.append(
                f"- [実測] {label}: avg={fmt(x.get('avg_ms'),'ms')} max={fmt(x.get('max_ms'),'ms')} "
                f"loss={fmt(x.get('loss_percent'),'%')}"
            )
    gw_avg, cf_avg, gg_avg = gw.get("avg_ms"), cf.get("avg_ms"), gg.get("avg_ms")
    gw_loss = gw.get("loss_percent")
    if gw_loss is not None and gw_loss > 0:
        out.append("- [推測] ゲートウェイ宛にロスがある → Wi-Fi/LAN側(電波・機器)の問題を疑う根拠になる")
    if gw_avg is not None and cf_avg is not None and gg_avg is not None:
        if gw_avg > 5 and (cf_avg - gw_avg) < gw_avg:
            out.append("- [推測] ゲートウェイ宛の遅延自体が大きい → Wi-Fi/LAN側がボトルネックの可能性")
        elif gw_avg <= 5 and cf_avg > 20 and gg_avg > 20:
            out.append("- [推測] LAN内は速いが外部宛が両方とも遅い → WAN側(回線/ISP)がボトルネックの可能性")
    return out


def lines_traceroute(d):
    tr = d.get("traceroute", {})
    out = []
    hop2_ips = set()
    for key, label in [("to_1_1_1_1", "1.1.1.1"), ("to_8_8_8_8", "8.8.8.8")]:
        t = tr.get(key, {})
        if t.get("error"):
            out.append(f"- [未検証] traceroute→{label}: {t['error']}")
            continue
        hops = t.get("hops", [])
        hop_str = ", ".join(f"#{h['hop']}:{h.get('ip') or '*'}({fmt(h.get('rtt_ms'),'ms')})" for h in hops)
        out.append(f"- [実測] traceroute→{label} 先頭4ホップ: {hop_str or 'データなし'}")
        for h in hops:
            if h["hop"] == 2 and h.get("ip") and h["ip"] != "*":
                hop2_ips.add(h["ip"])
    if hop2_ips:
        out.append(f"- [実測] 2ホップ目(ISP側最初の機器と推定): {', '.join(hop2_ips)}")
    else:
        out.append("- [推測] 2ホップ目が無応答(*) → ICMPフィルタの可能性と、経路上に機器がいない可能性を区別できない [要確認]")
    return out


def lines_dns(d):
    dns = d.get("dns", {})
    out = []
    for key, label in [("router", "ルーター"), ("cloudflare_1_1_1_1", "1.1.1.1"), ("google_8_8_8_8", "8.8.8.8")]:
        x = dns.get(key, {})
        if x.get("error"):
            out.append(f"- [未検証] DNS({label}): {x['error']}")
        else:
            out.append(f"- [実測] DNS({label}): avg={fmt(x.get('avg_ms'),'ms')} 失敗={x.get('failures')}/{x.get('samples')}")
    return out


def lines_throughput(d):
    th = d.get("throughput", {})
    if th.get("skipped"):
        return ["- [未検証] スループット計測をスキップした"]
    if th.get("error"):
        return [f"- [未検証] スループット計測失敗: {th['error']}"]
    out = []
    single = th.get("single_connection", {})
    par = th.get("parallel", {})
    single_mbps = single.get("mbps")
    par_mbps = par.get("aggregate_mbps")
    out.append(f"- [実測] 単一接続: {fmt(single_mbps,'Mbps')} ({fmt(single.get('bytes'),'',0)} bytes / {fmt(single.get('seconds'),'s',2)})")
    out.append(f"- [実測] 6並列合計: {fmt(par_mbps,'Mbps')} ({fmt(par.get('total_bytes'),'',0)} bytes / {fmt(par.get('wall_seconds'),'s',2)})")
    if single_mbps and par_mbps:
        ratio = par_mbps / single_mbps
        out.append(f"- [実測] 並列/単一 比率: {ratio:.2f}倍")
        if ratio >= 1.5:
            out.append("- [推測] 並列にすると大きく伸びる → 単一フローの上限(Wi-Fi再送やTCPウィンドウ等)が制限要因の可能性。回線自体の上限ではなさそう")
        else:
            out.append("- [推測] 並列にしても伸びない → 回線側(契約速度上限やISP側輻輳)の可能性。時間帯を変えて再測定すると輻輳か契約上限かの切り分けの助けになる [要確認]")
    return out


def lines_bufferbloat(d):
    bb = d.get("bufferbloat", {})
    if bb.get("skipped"):
        return ["- [未検証] バッファブロート計測をスキップした"]
    if not bb.get("supported"):
        return [f"- [未検証] {bb.get('note', 'networkQuality が使えない環境')}"]

    # macOS Sequoia以降は負荷時Responsivenessとアイドル時Idle Latencyで別々にRPMが出る。
    # 旧フォーマット(Uplink/Downlink別)しか無いJSONへは後方互換でフォールバックする。
    resp_cat = bb.get("responsiveness_category") or bb.get("downlink_responsiveness_category")
    resp_rpm = bb.get("responsiveness_rpm") if bb.get("responsiveness_rpm") is not None else bb.get("downlink_rpm")

    out = [
        f"- [実測] Responsiveness(負荷時): {resp_cat} ({fmt(resp_rpm,'RPM',0)}, {fmt(bb.get('responsiveness_loaded_latency_ms'),'ms')})",
        f"- [実測] Idle Latency(アイドル時): {fmt(bb.get('idle_latency_ms'),'ms')} ({fmt(bb.get('idle_latency_rpm'),'RPM',0)})",
        f"- [実測] Downlink容量: {fmt(bb.get('downlink_capacity_mbps'),'Mbps')} / Uplink容量: {fmt(bb.get('uplink_capacity_mbps'),'Mbps')}",
    ]
    if resp_cat and resp_cat.lower() in ("low", "poor"):
        out.append("- [推測] 負荷時Responsivenessが低カテゴリ → バッファブロートの疑い。速度が出ていても体感が悪くなる典型パターン")
    idle_rpm, load_rpm = bb.get("idle_latency_rpm"), resp_rpm
    if idle_rpm and load_rpm and load_rpm < idle_rpm * 0.5:
        out.append(
            f"- [実測] アイドル時RPM({idle_rpm})に対し負荷時RPM({load_rpm})が半分未満に低下 "
            "→ 回線が混雑すると遅延が急増するバッファブロートの典型的な数値パターン"
        )
    return out


def report_one(d, title):
    lines = [f"## {title} (label={d.get('meta', {}).get('label')}, {d.get('meta', {}).get('timestamp_utc')})", ""]
    lines.append("### Wi-Fi")
    lines += lines_wifi(d)
    lines.append("")
    lines.append("### IPv6")
    lines += lines_ipv6(d)
    lines.append("")
    lines.append("### 遅延")
    lines += lines_latency(d)
    lines.append("")
    lines.append("### 経路")
    lines += lines_traceroute(d)
    lines.append("")
    lines.append("### DNS")
    lines += lines_dns(d)
    lines.append("")
    lines.append("### スループット")
    lines += lines_throughput(d)
    lines.append("")
    lines.append("### バッファブロート")
    lines += lines_bufferbloat(d)
    lines.append("")
    return "\n".join(lines)


def diff_summary(before, after):
    def g(d, *path):
        cur = d
        for p in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur

    rows = [
        ("Wi-Fi SNR(dB)", ("wifi", "snr_db")),
        ("ゲートウェイ遅延avg(ms)", ("latency", "gateway", "avg_ms")),
        ("1.1.1.1遅延avg(ms)", ("latency", "cloudflare_1_1_1_1", "avg_ms")),
        ("単一DL(Mbps)", ("throughput", "single_connection", "mbps")),
        ("6並列DL(Mbps)", ("throughput", "parallel", "aggregate_mbps")),
        ("Downlink RPM", ("bufferbloat", "downlink_rpm")),
        ("Idle Latency(ms)", ("bufferbloat", "idle_latency_ms")),
    ]
    lines = ["## 前後比較", "", "| 指標 | before | after |", "| --- | --- | --- |"]
    for name, path in rows:
        b = g(before, *path)
        a = g(after, *path)
        lines.append(f"| {name} | {fmt(b)} | {fmt(a)} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="net_diag.py の結果JSONから指標を整理して表示する")
    ap.add_argument("file", nargs="?", help="単一ファイルを見る場合")
    ap.add_argument("--before", help="前後比較: before側のJSON")
    ap.add_argument("--after", help="前後比較: after側のJSON")
    args = ap.parse_args()

    out = []
    if args.before and args.after:
        b, a = load(args.before), load(args.after)
        out.append(report_one(b, "Before"))
        out.append(report_one(a, "After"))
        out.append(diff_summary(b, a))
    elif args.file:
        out.append(report_one(load(args.file), "計測結果"))
    else:
        ap.error("file か --before/--after のいずれかを指定してください")

    print("\n".join(out))


if __name__ == "__main__":
    main()
