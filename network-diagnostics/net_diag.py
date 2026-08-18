#!/usr/bin/env python3
"""自宅ネットワークの実測診断スクリプト。

Wi-Fi / IPv6 / 遅延 / 経路 / DNS / スループット / バッファブロートを一括計測し、
results/ に JSON で保存する。--label を変えて複数回実行すれば前後比較できる。

macOS (bash 3.2 環境と同じくBSD userland) と Linux の両方で動くことを意図しているが、
Wi-Fi のフィールド名は OS バージョンで変わりやすいため、パース失敗時は生出力を
"raw" に必ず残す。バッファブロート計測 (networkQuality) は macOS 専用コマンド。

実行にはこのマシンが実際に自宅Wi-Fi/ルーターに接続されている必要がある
(クラウド上やVPN経由での実行では自宅回線の実測にならない)。
"""

import argparse
import concurrent.futures
import json
import platform
import random
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

DEFAULT_THROUGHPUT_URL = "https://speed.cloudflare.com/__down?bytes={bytes}"


def run(cmd, timeout=15):
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return None, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return None, "", f"timeout after {timeout}s: {' '.join(cmd)}"


def section(name):
    def deco(fn):
        def wrapper(*a, **kw):
            print(f"[*] {name} を計測中...", file=sys.stderr)
            try:
                return fn(*a, **kw)
            except Exception as e:  # 1セクションの失敗で全体を止めない
                return {"error": f"{type(e).__name__}: {e}"}
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# 共通: デフォルトゲートウェイ

def get_default_gateway():
    if IS_LINUX:
        rc, out, err = run(["ip", "route", "show", "default"])
        m = re.search(r"default via (\S+) dev (\S+)", out)
        if m:
            return {"ip": m.group(1), "iface": m.group(2)}
    elif IS_MACOS:
        rc, out, err = run(["route", "-n", "get", "default"])
        ip_m = re.search(r"gateway:\s*(\S+)", out)
        iface_m = re.search(r"interface:\s*(\S+)", out)
        if ip_m:
            return {"ip": ip_m.group(1), "iface": iface_m.group(1) if iface_m else None}
    return {"ip": None, "iface": None, "error": "デフォルトゲートウェイを特定できなかった"}


# ---------------------------------------------------------------------------
# 1. Wi-Fi

def _parse_wifi_macos(text):
    info = {"raw": text}
    m = re.search(r"PHY Mode:\s*(\S+)", text)
    info["standard"] = m.group(1) if m else None
    m = re.search(r"Channel:\s*(\d+)\s*\(([\d.]+GHz)(?:,\s*(\d+)MHz)?\)", text)
    if m:
        info["channel"] = int(m.group(1))
        info["band"] = m.group(2)
        info["bandwidth_mhz"] = int(m.group(3)) if m.group(3) else None
    else:
        info["channel"] = info["band"] = info["bandwidth_mhz"] = None
    m = re.search(r"Signal\s*/\s*Noise:\s*(-?\d+)\s*dBm\s*/\s*(-?\d+)\s*dBm", text)
    if m:
        info["rssi_dbm"] = int(m.group(1))
        info["noise_dbm"] = int(m.group(2))
        info["snr_db"] = info["rssi_dbm"] - info["noise_dbm"]
    else:
        info["rssi_dbm"] = info["noise_dbm"] = info["snr_db"] = None
    m = re.search(r"Transmit Rate:\s*(\d+)", text)
    info["link_speed_mbps"] = int(m.group(1)) if m else None
    return info


@section("Wi-Fi")
def get_wifi_info():
    if IS_MACOS:
        rc, out, err = run(["system_profiler", "SPAirPortDataType"], timeout=20)
        if rc != 0 and not out:
            return {"error": f"system_profiler 失敗: {err}"}
        return _parse_wifi_macos(out)

    if IS_LINUX:
        if not shutil.which("iw"):
            return {"error": "iw コマンドが見つからない (iproute2/wireless-tools を導入してください)"}
        rc, dev_out, _ = run(["iw", "dev"])
        m = re.search(r"Interface\s+(\S+)", dev_out)
        if not m:
            return {"error": "Wi-Fi インターフェースが見つからない"}
        iface = m.group(1)

        rc, link_out, _ = run(["iw", "dev", iface, "link"])
        rc, info_out, _ = run(["iw", "dev", iface, "info"])
        rc, survey_out, _ = run(["iw", "dev", iface, "survey", "dump"])

        info = {"iface": iface, "raw": {"link": link_out, "info": info_out, "survey": survey_out}}

        m = re.search(r"signal:\s*(-?\d+)\s*dBm", link_out)
        info["rssi_dbm"] = int(m.group(1)) if m else None

        m = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s(.*)", link_out)
        info["link_speed_mbps"] = float(m.group(1)) if m else None
        rate_extra = m.group(2) if m else ""
        if "HE-MCS" in rate_extra:
            info["standard"] = "802.11ax (Wi-Fi 6)"
        elif "VHT-MCS" in rate_extra:
            info["standard"] = "802.11ac (Wi-Fi 5)"
        elif "MCS" in rate_extra:
            info["standard"] = "802.11n (Wi-Fi 4)"
        else:
            info["standard"] = None

        m = re.search(r"channel:\s*(\d+)\s*\((\d+)\s*MHz\),\s*width:\s*(\d+)\s*MHz", info_out)
        if m:
            info["channel"] = int(m.group(1))
            info["freq_mhz"] = int(m.group(2))
            info["bandwidth_mhz"] = int(m.group(3))
        else:
            info["channel"] = info["freq_mhz"] = info["bandwidth_mhz"] = None

        noise = None
        for block in survey_out.split("\n\n"):
            if "[in use]" in block:
                nm = re.search(r"noise:\s*(-?\d+)\s*dBm", block)
                if nm:
                    noise = int(nm.group(1))
                break
        info["noise_dbm"] = noise
        info["snr_db"] = (info["rssi_dbm"] - noise) if (info["rssi_dbm"] is not None and noise is not None) else None
        return info

    return {"error": f"未対応OS: {platform.system()}"}


# ---------------------------------------------------------------------------
# 2. IPv6

@section("IPv6")
def get_ipv6_info(gateway_iface):
    info = {"global_addresses": [], "unique_local_addresses": [], "has_default_route": False}

    if IS_LINUX:
        rc, addr_out, _ = run(["ip", "-6", "addr", "show", "scope", "global"])
        info["global_addresses"] = re.findall(r"inet6\s+([0-9a-fA-F:]+)/\d+", addr_out)
        rc, route_out, _ = run(["ip", "-6", "route", "show", "default"])
        info["has_default_route"] = bool(route_out.strip())
        info["raw"] = {"addr": addr_out, "route": route_out}
    elif IS_MACOS:
        rc, ifc_out, _ = run(["ifconfig"])
        for m in re.finditer(r"inet6\s+([0-9a-fA-F:]+)(?:%\S+)?\s", ifc_out):
            addr = m.group(1)
            if addr.startswith("fe80"):
                continue
            elif addr.startswith(("fc", "fd")):
                info["unique_local_addresses"].append(addr)
            else:
                info["global_addresses"].append(addr)
        rc, route_out, _ = run(["netstat", "-rn", "-f", "inet6"])
        info["has_default_route"] = bool(re.search(r"^default\s", route_out, re.MULTILINE))
        info["raw"] = {"ifconfig": ifc_out, "route": route_out}
    else:
        return {"error": f"未対応OS: {platform.system()}"}

    info["has_global_address"] = len(info["global_addresses"]) > 0
    return info


# ---------------------------------------------------------------------------
# 3. 遅延 (ping)

def ping_host(host, count=10):
    if IS_MACOS:
        cmd = ["ping", "-c", str(count), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", "1", host]
    rc, out, err = run(cmd, timeout=count * 2 + 15)
    if rc is None:
        return {"error": err, "raw": out}

    loss_m = re.search(r"([\d.]+)%\s*packet loss", out)
    stats_m = re.search(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)", out)
    return {
        "target": host,
        "min_ms": float(stats_m.group(1)) if stats_m else None,
        "avg_ms": float(stats_m.group(2)) if stats_m else None,
        "max_ms": float(stats_m.group(3)) if stats_m else None,
        "loss_percent": float(loss_m.group(1)) if loss_m else None,
        "raw": out,
    }


@section("遅延 (ping)")
def get_latency_info(gateway_ip):
    targets = {"gateway": gateway_ip, "cloudflare_1_1_1_1": "1.1.1.1", "google_8_8_8_8": "8.8.8.8"}
    result = {}
    for label, host in targets.items():
        if not host:
            result[label] = {"error": "対象IPが不明"}
            continue
        result[label] = ping_host(host)
    return result


# ---------------------------------------------------------------------------
# 4. 経路 (traceroute 先頭4ホップ)

def traceroute_first_n(host, n=4):
    if shutil.which("traceroute"):
        cmd = ["traceroute", "-m", str(n), "-q", "1", "-w", "2", host]
    elif shutil.which("tracepath"):
        cmd = ["tracepath", "-m", str(n), host]
    else:
        return {"error": "traceroute/tracepath が見つからない"}

    rc, out, err = run(cmd, timeout=n * 5 + 15)
    hops = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if not m:
            continue
        hop_num = int(m.group(1))
        if hop_num > n:
            continue
        rest = m.group(2)
        ip_m = re.search(r"\(([0-9a-fA-F.:]+)\)", rest)
        rtt_m = re.search(r"([\d.]+)\s*ms", rest)
        hops.append({
            "hop": hop_num,
            "ip": ip_m.group(1) if ip_m else ("*" if "*" in rest else None),
            "rtt_ms": float(rtt_m.group(1)) if rtt_m else None,
            "raw": rest.strip(),
        })
    return {"hops": hops, "raw": out}


@section("経路 (traceroute)")
def get_traceroute_info():
    return {
        "to_1_1_1_1": traceroute_first_n("1.1.1.1", 4),
        "to_8_8_8_8": traceroute_first_n("8.8.8.8", 4),
    }


# ---------------------------------------------------------------------------
# 5. DNS (自前UDPクエリで応答時間のみ測る。dig等の外部コマンドに依存しない)

def _build_dns_query(hostname):
    tid = random.randint(0, 65535)
    header = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    question = b""
    for part in hostname.split("."):
        question += struct.pack("B", len(part)) + part.encode("ascii")
    question += b"\x00" + struct.pack(">HH", 1, 1)  # type A, class IN
    return header + question, tid


def dns_query_once(server_ip, hostname, timeout=3.0):
    packet, tid = _build_dns_query(hostname)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        start = time.perf_counter()
        sock.sendto(packet, (server_ip, 53))
        data, _ = sock.recvfrom(512)
        elapsed_ms = (time.perf_counter() - start) * 1000
        resp_tid = struct.unpack(">H", data[0:2])[0]
        if resp_tid != tid:
            return None
        return elapsed_ms
    except socket.timeout:
        return None
    finally:
        sock.close()


def dns_query_stats(server_ip, hostname, samples=5):
    if not server_ip:
        return {"error": "サーバIPが不明"}
    times = []
    failures = 0
    for _ in range(samples):
        t = dns_query_once(server_ip, hostname)
        if t is None:
            failures += 1
        else:
            times.append(t)
    return {
        "server": server_ip,
        "hostname": hostname,
        "samples": samples,
        "failures": failures,
        "avg_ms": sum(times) / len(times) if times else None,
        "min_ms": min(times) if times else None,
        "max_ms": max(times) if times else None,
        "raw_ms": times,
    }


@section("DNS")
def get_dns_info(gateway_ip, hostname="example.com"):
    return {
        "router": dns_query_stats(gateway_ip, hostname),
        "cloudflare_1_1_1_1": dns_query_stats("1.1.1.1", hostname),
        "google_8_8_8_8": dns_query_stats("8.8.8.8", hostname),
        "note": "ルーターDNS = デフォルトゲートウェイIPと仮定 (多くの家庭用ルーターはLAN側でDNSプロキシを兼ねる)",
    }


# ---------------------------------------------------------------------------
# 6. スループット

def download_bytes(url, max_bytes, timeout):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "net-diag/1.0"})
    total = 0
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes and total >= max_bytes:
                break
    elapsed = time.perf_counter() - start
    return total, elapsed


def single_connection_test(url_template, size_mb, timeout):
    max_bytes = size_mb * 1024 * 1024
    url = url_template.format(bytes=max_bytes) if "{bytes}" in url_template else url_template
    total, elapsed = download_bytes(url, max_bytes, timeout)
    mbps = (total * 8 / 1_000_000) / elapsed if elapsed > 0 else None
    return {"url": url, "bytes": total, "seconds": elapsed, "mbps": mbps}


def parallel_connection_test(url_template, size_mb_each, n, timeout):
    max_bytes = size_mb_each * 1024 * 1024
    url = url_template.format(bytes=max_bytes) if "{bytes}" in url_template else url_template
    results = [None] * n
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(download_bytes, url, max_bytes, timeout): i for i in range(n)}
        for fut in concurrent.futures.as_completed(futs):
            i = futs[fut]
            try:
                total, elapsed = fut.result()
                results[i] = {"bytes": total, "seconds": elapsed}
            except Exception as e:
                results[i] = {"error": str(e)}
    wall = time.perf_counter() - start
    total_bytes = sum(r["bytes"] for r in results if r and "bytes" in r)
    mbps = (total_bytes * 8 / 1_000_000) / wall if wall > 0 else None
    return {"url": url, "per_connection": results, "total_bytes": total_bytes, "wall_seconds": wall, "aggregate_mbps": mbps}


@section("スループット")
def get_throughput_info(url_template, single_mb, parallel_mb_each, parallel_n, timeout):
    return {
        "single_connection": single_connection_test(url_template, single_mb, timeout),
        "parallel": parallel_connection_test(url_template, parallel_mb_each, parallel_n, timeout),
    }


# ---------------------------------------------------------------------------
# 7. バッファブロート (networkQuality, macOS専用)

@section("バッファブロート (networkQuality)")
def get_bufferbloat_info():
    if not (IS_MACOS and shutil.which("networkQuality")):
        return {
            "supported": False,
            "note": "networkQuality は macOS 専用コマンドのため、この環境では測定できない (未検証)",
        }
    rc, out, err = run(["networkQuality", "-v"], timeout=60)
    if rc is None:
        return {"supported": True, "error": err, "raw": out}

    result = {"supported": True, "raw": out}
    ul = re.search(r"Uplink Responsiveness:\s*(\S+)\s*\((\d+)\s*RPM\)", out)
    dl = re.search(r"Downlink Responsiveness:\s*(\S+)\s*\((\d+)\s*RPM\)", out)
    ulcap = re.search(r"Uplink capacity:\s*([\d.]+)\s*Mbps", out)
    dlcap = re.search(r"Downlink capacity:\s*([\d.]+)\s*Mbps", out)
    idle = re.search(r"Idle Latency:\s*([\d.]+)\s*m", out, re.IGNORECASE)

    result["uplink_responsiveness_category"] = ul.group(1) if ul else None
    result["uplink_rpm"] = int(ul.group(2)) if ul else None
    result["downlink_responsiveness_category"] = dl.group(1) if dl else None
    result["downlink_rpm"] = int(dl.group(2)) if dl else None
    result["uplink_capacity_mbps"] = float(ulcap.group(1)) if ulcap else None
    result["downlink_capacity_mbps"] = float(dlcap.group(1)) if dlcap else None
    result["idle_latency_ms"] = float(idle.group(1)) if idle else None
    return result


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="自宅ネットワーク実測診断")
    parser.add_argument("--label", required=True, help="この計測を識別するラベル (例: before, after-router-reboot)")
    parser.add_argument("--out-dir", default=str(Path(__file__).parent / "results"))
    parser.add_argument("--dns-hostname", default="example.com")
    parser.add_argument("--throughput-url", default=DEFAULT_THROUGHPUT_URL,
                         help="{bytes} を含む場合はサイズが埋め込まれる (既定: Cloudflare speed test)")
    parser.add_argument("--single-mb", type=int, default=100, help="単一接続テストのダウンロードサイズ(MB)")
    parser.add_argument("--parallel-mb", type=int, default=50, help="並列テスト1接続あたりのサイズ(MB)")
    parser.add_argument("--parallel-n", type=int, default=6)
    parser.add_argument("--throughput-timeout", type=int, default=60)
    parser.add_argument("--skip-throughput", action="store_true")
    parser.add_argument("--skip-bufferbloat", action="store_true")
    args = parser.parse_args()

    if platform.system() not in ("Darwin", "Linux"):
        print(f"[warn] 未検証のOS: {platform.system()} (macOS/Linux想定)", file=sys.stderr)

    gateway = get_default_gateway()
    gateway_ip = gateway.get("ip")

    result = {
        "meta": {
            "label": args.label,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
        "gateway": gateway,
        "wifi": get_wifi_info(),
        "ipv6": get_ipv6_info(gateway.get("iface")),
        "latency": get_latency_info(gateway_ip),
        "traceroute": get_traceroute_info(),
        "dns": get_dns_info(gateway_ip, args.dns_hostname),
    }

    if args.skip_throughput:
        result["throughput"] = {"skipped": True}
    else:
        result["throughput"] = get_throughput_info(
            args.throughput_url, args.single_mb, args.parallel_mb, args.parallel_n, args.throughput_timeout
        )

    if args.skip_bufferbloat:
        result["bufferbloat"] = {"skipped": True}
    else:
        result["bufferbloat"] = get_bufferbloat_info()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^A-Za-z0-9_\-]+", "_", args.label)
    ts = result["meta"]["timestamp_utc"].replace(":", "").replace("-", "")
    out_path = out_dir / f"{ts}_{safe_label}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[ok] 保存先: {out_path}", file=sys.stderr)
    return result


if __name__ == "__main__":
    main()
