"""SNS 戦略分析エージェント — 全コンポーネント統合のデモ。

実行方法:
    # オフラインデモ(MockLLMClient、API キー不要)
    python examples/sns_strategy_agent.py

    # 実際の Claude API で実行
    python examples/sns_strategy_agent.py --live
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fable5 import MockLLMClient, Orchestrator

TARGET_COMPANIES = ["競合A社", "競合B社", "競合C社"]

MOCK_RESPONSES = [
    # Phase 1: planning
    "# タスク分解\n- 各社のSNSデータ収集\n- 投稿頻度・エンゲージメント率の比較\n- 戦略提案の作成",
    # Phase 2: research
    "# データ収集結果\n- 競合A社: 投稿頻度 週5回、エンゲージメント率 2.1%\n"
    "- 競合B社: 投稿頻度 週3回、エンゲージメント率 3.4%\n"
    "- 競合C社: 投稿頻度 毎日、エンゲージメント率 1.2%",
    # Phase 3: analysis
    "# 競合SNS戦略分析\n\n## 比較表\n- 投稿頻度: B社は少数精鋭、C社は物量型\n"
    "- エンゲージメント率: B社が最も高い(3.4%)\n\n## 示唆\n"
    "1. 投稿頻度よりも質がエンゲージメントを左右する\n"
    "2. 週3〜5回の高品質投稿が最適\n3. 動画コンテンツの比率を上げる",
    # Phase 4: final report
    "# 最終戦略レポート\n\n## エグゼクティブサマリー\n"
    "競合3社の分析から、投稿頻度とエンゲージメント率は逆相関の傾向。\n\n"
    "## コンテンツカレンダー提案\n- 月・水・金: 教育系コンテンツ\n"
    "- 火・木: エンゲージメント促進(問いかけ型)\n\n"
    "## KPI\n- エンゲージメント率 3.0% 以上を目標",
]


def build_orchestrator(live: bool) -> Orchestrator:
    if live:
        return Orchestrator(
            session_id="sns_analysis_live", budget_usd=5.0, use_llm_verifier=True,
            goal="競合3社のSNS戦略を分析し、来月のコンテンツ戦略を提案する",
        )
    return Orchestrator(
        session_id="sns_analysis_demo",
        llm=MockLLMClient(MOCK_RESPONSES),
        base_dir=".fable5-demo",
        budget_usd=5.0,
    )


def main() -> None:
    live = "--live" in sys.argv
    orch = build_orchestrator(live)

    companies = "、".join(TARGET_COMPANIES)
    phases = [
        {
            "id": "planning",
            "task": {
                "type": "planning",
                "description": f"{companies} のSNS戦略分析タスクを実行可能なサブタスクに分解する",
                "min_chars": 30,
            },
        },
        {
            "id": "research",
            "task": {
                "type": "analysis",
                "description": f"{companies} のSNS投稿データ(投稿頻度・エンゲージメント率)を調査しまとめる",
                "required_keywords": ["投稿頻度", "エンゲージメント"],
                "min_chars": 50,
            },
            "on_failure": "skip_and_continue",
        },
        {
            "id": "analysis",
            "task": {
                "type": "analysis",
                "description": "収集したSNSデータを戦略的に分析し、自社への示唆を3点以上挙げる",
                "required_keywords": ["エンゲージメント", "示唆"],
                "min_chars": 100,
            },
        },
        {
            "id": "final_report",
            "task": {
                "type": "writing",
                "description": "クライアント提出用の最終SNS戦略レポートを最高品質で作成する",
                "required_quality": "critical",
                "required_keywords": ["サマリー", "KPI"],
                "min_chars": 100,
            },
        },
    ]

    print(f"=== SNS 戦略分析 ({'LIVE' if live else 'MOCK'}) ===\n")
    results = orch.run_workflow(phases)

    for phase_id, result in results.items():
        if isinstance(result, dict):  # チェックポイントからの再開
            print(f"[{phase_id}] (resumed) score={result.get('score')}")
            continue
        print(
            f"[{phase_id}] {result.status} "
            f"model={result.routing.model} "
            f"score={result.final_score:.2f} "
            f"attempts={result.attempts} "
            f"cost=${result.cost_usd:.4f}"
        )

    print(f"\n総コスト: ${orch.state.get_total_cost():.4f}")
    print(f"STATE.md: {orch.state.md_path}")

    new_skills = orch.improve()
    if new_skills:
        print(f"自動生成されたスキル: {[s.name for s in new_skills]}")


if __name__ == "__main__":
    main()
