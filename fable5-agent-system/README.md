# 自己改善型 AI エージェントシステム

> **休止中(2026-07-15)**: 2026-07-11 の作成以降、実運用・追加コミットともになし。
> 続けるか閉じるかは未確定。着手前にこのREADMEの更新日を確認すること。

「動くAI」ではなく「実行のたびに賢くなるAI」を目指した、Claude API 上の
自己改善型エージェントシステムの実装です。

## ⚠️ はじめに — 元記事についての重要な訂正

このプロジェクトは X の記事「【Claude Fable 5】無料期間で構築する自己改善型AIエージェントシステム」
のアーキテクチャを参考に実装していますが、記事にはいくつかの事実誤認があります:

- **「Fable 5」はエージェントフレームワークではありません。** Anthropic の
  最上位 LLM(モデル)の名前であり、LangChain のようなオーケストレーション
  フレームワークは存在しません。記事が説明する Router / Verification Loop /
  Memory / Skills といった構成要素は、フレームワークの機能ではなく
  **自分で実装する設計パターン**です(本リポジトリがその実装です)。
- **記事中のモデル ID は架空です。** `claude-opus-5`・`claude-haiku-5`・
  `gpt-5.5`・`codex-2026` などは実在しません。本実装では実在する
  `claude-opus-4-8` / `claude-sonnet-5` / `claude-haiku-4-5` を使用し、
  料金も実際の価格($5/$25、$3/$15、$1/$5 per 1M tokens)に基づいています。
- 記事中の「7月7日までの無料期間」も Anthropic の公式発表とは確認できません。
  API 利用は通常の従量課金です。

アーキテクチャの考え方(検証ループ・メモリ・スキル蓄積・状態管理)自体は
妥当な設計パターンなので、それを実際に動くコードとして実装しています。

## アーキテクチャ

```
Orchestrator
├── Router               # タスクの複雑度・種別からモデルを動的選択(+学習)
├── VerificationEngine   # 出力品質の自動検証と改善指示の生成
├── ExecutionLoop        # Executor → Verifier → 改善再試行 のループ
├── MemoryStore          # 作業記憶 + エピソード記憶(JSON 永続化・類似検索)
├── SkillsLibrary        # 再利用可能スキル(手続き記憶)
├── SkillAutoGenerator   # 成功パターンのスキル自動生成(Level 4 自己改善)
├── StateManager         # チェックポイント・再開・コスト上限(STATE.md 出力)
└── DriftMonitor         # 目標からの逸脱検知
```

### 自己改善の4レベルとの対応

| レベル | 内容 | 実装 |
|---|---|---|
| 1 | プロンプト自己修正 | `ExecutionLoop` — 検証不合格時に改善指示を注入して再試行 |
| 2 | モデル選択の最適化 | `Router` + `MemoryStore.get_best_model_for_type()` |
| 3 | ワークフローの再構成 | `Orchestrator.run_workflow()` のチェックポイント再開 |
| 4 | 新スキルの自律生成 | `SkillAutoGenerator.scan_and_generate()` |

## 使用モデル

| 用途 | モデル | 入力/出力($ per 1M tokens) |
|---|---|---|
| 最終成果物・CRITICAL タスク | `claude-opus-4-8` | $5.00 / $25.00 |
| 分析・計画・コード(標準) | `claude-sonnet-5` | $3.00 / $15.00 |
| 検証・単純タスク | `claude-haiku-4-5` | $1.00 / $5.00 |

Opus 4.8 / Sonnet 5 では adaptive thinking(`thinking: {"type": "adaptive"}`)と
`output_config.effort` を利用します(Haiku 4.5 は非対応のため自動的に省略)。

## セットアップ

```bash
cd fable5-agent-system
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...   # 実 API を使う場合
```

## 使い方

```python
from fable5 import Orchestrator

orch = Orchestrator(
    session_id="sns_analysis_001",
    budget_usd=5.0,            # コスト上限(超過で CostLimitExceeded)
    use_llm_verifier=True,     # Haiku による LLM 検証を重ねる
    goal="競合3社のSNS戦略を分析し来月のコンテンツ戦略を提案する",
)

result = orch.run_task({
    "type": "analysis",
    "description": "競合3社のSNS戦略を分析し、比較表と示唆をまとめる",
    "required_keywords": ["投稿頻度", "エンゲージメント"],
    "min_chars": 300,
})
print(result.status, result.final_score, result.routing.model)

# 夜間バッチ等で: 成功パターンをスキル化
orch.improve()
```

複数フェーズのワークフロー(チェックポイントから再開可能):

```python
results = orch.run_workflow([
    {"id": "research", "task": {...}},
    {"id": "analysis", "task": {...}, "on_failure": "skip_and_continue"},
    {"id": "final_report", "task": {"required_quality": "critical", ...}},
])
```

## デモ

API キー不要のオフラインデモ(MockLLMClient 使用):

```bash
python examples/sns_strategy_agent.py          # モック実行
python examples/sns_strategy_agent.py --live   # 実 API で実行
```

## テスト

```bash
python -m pytest tests/ -v
```

36 テスト。すべて MockLLMClient を使いネットワーク・API キーなしで動作します。

## 実行時に生成されるファイル

```
.fable5/
├── memory/episodic.json          # エピソード記憶(最新1000件)
├── skills.json                   # スキルライブラリ
└── sessions/<session_id>/
    ├── state.json                # 機械可読の状態(再開用)
    └── STATE.md                  # 人間可読の実行状態レポート
```

## 本番運用の注意

- **コスト上限は必ず設定する** — `budget_usd` 超過で `CostLimitExceeded` が送出され、
  ステータスが `halted_cost_limit` になります。
- **Verifier は Executor と別モデルに** — 既定では Haiku 4.5 を使用します
  (同一モデルは同じバイアスを持つため)。
- **エスカレーション** — `max_retries` 超過時は最良の出力を添えて
  `status="escalate"` を返し、人間の判断に委ねます。自動でリトライし続けません。
