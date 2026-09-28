"""コマンドライン入口。

  python -m meta_autopilot.cli -c config.yaml init-bq
  python -m meta_autopilot.cli -c config.yaml daily            # 取り込み→検知→新CR判定→Slack
  python -m meta_autopilot.cli -c config.yaml analyze-pending  # 未解析CRをマルチモーダル解析
  python -m meta_autopilot.cli -c config.yaml mine -o out/patterns.json
  python -m meta_autopilot.cli -c config.yaml generate --pattern out/pattern.json --facts facts.txt -o out/script.json
  python -m meta_autopilot.cli -c config.yaml render --script out/script.json --assets assets/ -o out/cr.mp4
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="meta_autopilot")
    ap.add_argument("-c", "--config", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-bq")
    sub.add_parser("ingest")
    sub.add_parser("detect")
    sub.add_parser("daily")
    ana = sub.add_parser("analyze-pending")
    ana.add_argument("--limit", type=int, default=20)
    m = sub.add_parser("mine")
    m.add_argument("-o", "--out", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--pattern", required=True, help="mine の出力から1件を抜き出した JSON")
    g.add_argument("--facts", required=True, help="使ってよい事実(1行1件)。数字はここにあるものしか使わせない")
    g.add_argument("-o", "--out", required=True)
    r = sub.add_parser("render")
    r.add_argument("--script", required=True)
    r.add_argument("--assets", required=True)
    r.add_argument("--tts-command", help="{text_file} と {out} を含むTTSコマンド。未指定なら無音(確認用)")
    r.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)

    from . import pipeline

    if args.cmd == "init-bq":
        from .ingest import bq

        for f in ("01_tables.sql", "10_views.sql"):
            bq.apply_sql_file(cfg.gcp_project, cfg.bq_dataset, f)
        print("BigQuery のテーブル・ビューを作成しました")
    elif args.cmd == "ingest":
        print(pipeline.ingest(cfg))
    elif args.cmd == "detect":
        alerts = pipeline.detect(cfg)
        pipeline.notify(cfg, alerts, header=f"Meta広告 異常検知 {len(alerts)}件")
        print(f"{len(alerts)} 件")
    elif args.cmd == "daily":
        counts = pipeline.ingest(cfg)
        alerts = pipeline.detect(cfg)
        decisions = pipeline.lifecycle(cfg)
        alerts += pipeline.lifecycle_alerts(decisions)
        mode = "(dry-run: Meta への書き込みなし)" if cfg.dry_run else ""
        pipeline.notify(cfg, alerts, header=f"Meta広告デイリー 異常{len(alerts)}件{mode}")
        print({"ingested": counts, "alerts": len(alerts), "decisions": len(decisions)})
    elif args.cmd == "analyze-pending":
        _analyze_pending(cfg, args.limit)
    elif args.cmd == "mine":
        from .ingest import bq
        from .patterns.mine import mine_patterns

        rows = bq.query(cfg.gcp_project, f"SELECT * FROM `{cfg.gcp_project}.{cfg.bq_dataset}.v_creative_performance`")
        stats = mine_patterns(rows, **cfg.generation.get("mine", {}))
        pipeline.write_json(Path(args.out), [asdict(s) | {"label": s.label()} for s in stats])
        print(f"仮説候補 {len(stats)} 件 → {args.out}")
    elif args.cmd == "generate":
        from .generate.script import check_pattern, generate_script, validate_facts

        pat = json.loads(Path(args.pattern).read_text(encoding="utf-8"))
        facts = [x.strip() for x in Path(args.facts).read_text(encoding="utf-8").splitlines() if x.strip()]
        pattern = dict(pat["conditions"])
        hypothesis = pat.get("hypothesis") or f"{pat.get('label', pattern)} の組み合わせは CPA を改善する"
        script = generate_script(
            pattern, pat.get("control_features", {}), facts, hypothesis,
            model=cfg.generation.get("script_model", "claude-opus-5-5"),
        )
        problems = validate_facts(script, facts) + check_pattern(script, pattern)
        pipeline.write_json(Path(args.out), {"script": script.model_dump(), "problems": problems})
        print("要修正: " + " / ".join(problems) if problems else f"台本OK → {args.out}(入稿前に人が確認すること)")
    elif args.cmd == "render":
        from .generate.assemble import render, resolve
        from .generate.script import VideoScript
        from .generate.tts import CommandTTS, SilentTTS

        data = json.loads(Path(args.script).read_text(encoding="utf-8"))
        if data.get("problems"):
            raise SystemExit("台本に未解決の問題があるためレンダリングしません: " + " / ".join(data["problems"]))
        script = VideoScript.model_validate(data["script"])
        tts = CommandTTS(args.tts_command) if args.tts_command else SilentTTS()
        work = Path(tempfile.mkdtemp(prefix="render_"))
        scenes = resolve(script, Path(args.assets), tts, work)
        print(render(script, scenes, work, Path(args.out)))


def _analyze_pending(cfg, limit: int) -> None:
    from .creative import analyzer, frames
    from .ingest import bq
    from .ingest.meta_insights import download, fetch_ad_creatives, video_source_url

    ds = f"{cfg.gcp_project}.{cfg.bq_dataset}"
    pending = bq.query(
        cfg.gcp_project,
        f"""SELECT r.ad_id, ANY_VALUE(r.account_id) AS account_id, SUM(r.spend) AS spend
            FROM `{ds}.raw_ad_daily` r LEFT JOIN `{ds}.creative_features` f USING (ad_id)
            WHERE f.ad_id IS NULL GROUP BY r.ad_id ORDER BY spend DESC LIMIT @limit""",
        {"limit": limit},
    )
    acc_of = {p["ad_id"]: p["account_id"] for p in pending}
    model = cfg.generation.get("analyzer_model", "claude-opus-5-5")
    out_rows = []
    for c in fetch_ad_creatives(list(acc_of), access_token=cfg.meta_access_token, api_version=cfg.graph_api_version):
        work = Path(tempfile.mkdtemp(prefix="cr_"))
        text = " / ".join(x for x in (c.get("title"), c.get("body")) if x)
        try:
            if c.get("video_id"):
                src = video_source_url(c["video_id"], access_token=cfg.meta_access_token, api_version=cfg.graph_api_version)
                if not src:
                    print(f"skip {c['ad_id']}: 動画URLが取得できない")
                    continue
                video = work / "v.mp4"
                download(src, video)
                info = frames.probe(video)
                inp = analyzer.AnalyzerInput(
                    creative_id=c["id"], media_type="video",
                    frames=frames.extract_frames(video, work / "frames", frames.sample_times(info["duration"])),
                    ad_text=text, measured_duration=info["duration"],
                    measured_cut_times=frames.scene_cut_times(video),
                    aspect_ratio_hint=analyzer.aspect_ratio_label(info["width"], info["height"]),
                )
            elif c.get("image_url") or c.get("thumbnail_url"):
                img = work / "i.jpg"
                download(c.get("image_url") or c["thumbnail_url"], img)
                inp = analyzer.AnalyzerInput(creative_id=c["id"], media_type="image", frames=[(0.0, img)], ad_text=text)
            else:
                print(f"skip {c['ad_id']}: 素材が取得できない(動的CR等)")
                continue
            feats = analyzer.analyze(inp, model=model)
        except Exception as e:  # 1件の失敗で全体を止めない
            print(f"失敗 {c['ad_id']}: {e}")
            continue
        out_rows.append(
            analyzer.to_bq_row(c["id"], c["ad_id"], acc_of[c["ad_id"]], feats, model=model,
                               analyzed_at=datetime.now(timezone.utc).isoformat())
        )
    bq.insert_rows(cfg.gcp_project, cfg.bq_dataset, "creative_features", out_rows)
    print(f"解析 {len(out_rows)} 件")


if __name__ == "__main__":
    main()
