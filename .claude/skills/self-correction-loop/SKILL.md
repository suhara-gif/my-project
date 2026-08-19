---
name: self-correction-loop
description: Claude Code で「自己修正ループ(Evaluator-Optimizerパターン)」を設計・構築したいときに使う。人間が完了条件だけを設計し、AIが作成→検査→問題特定→修正→再検査を回す仕組み。Manager/Builder/Judgeの役割分担、/goal によるLevel 1、BuilderとJudgeのSubagent連携によるLevel 2、CLAUDE.md・Skill・Hookで固定化するLevel 3の3段階の構築方法と、無限ループ防止・部分修正・人間の最終確認などの安全運用ルール、4週間の導入ロードマップをまとめる。「自己修正ループ」「Evaluator-Optimizer」「Builder Judge」「PASS FAIL RETRY ESCALATE」「検査役と作成役を分けたい」といった相談で呼ぶ。
---

# self-correction-loop — 自己修正ループ(Evaluator-Optimizerパターン)

## 目的

従来のAI活用は、人間が毎回成果物を確認し修正指示を出すため、**人間がボトルネック**になる。
自己修正ループは、人間が「何を正解とするか(完了条件)」だけを設計し、AIが
**作成→検査→問題特定→修正→再検査**を人間の介在なしに回す仕組み。人間の役目は
「正解の定義」と「リスクに応じた最終確認」に絞られる。

## 概念

- **作成役と検査役を分ける**のが核。同じエージェントが作って自分で採点すると、
  自分のミスに気づけない(確証バイアス)。
- 検査役には**Ground Truth(元資料・テスト結果・実行ログなど)**を持たせる。
  検査役の判定根拠が「なんとなく良さそう」では、ループ全体が信頼できなくなる。

## 役割

| 役割 | 責務 |
|---|---|
| **Manager** | ループ全体の進行管理。PASS / RETRY / ESCALATE を判断し、次の一手を決める。 |
| **Builder** | 成果物の作成・修正を行う。編集権限を持つのはこの役割だけ。 |
| **Judge** | 編集権限を持たない。Ground Truthに基づき PASS / FAIL / UNVERIFIED を判定するだけ。 |

Judge に編集権限を与えない(与えると Builder と癒着し、自己採点と同じ弱点に戻る)。

## 構築レベル

小さく始めて、必要になったら次のレベルへ進む。いきなり Level 3 を作らない。

### Level 1: 単一会話内の完了条件追従

1つの会話の中で `/goal` を使い、完了条件を明示してからタスクを進める。
Manager/Builder/Judge を分離せず、同一エージェントが完了条件と自分の出力を照合する
最も軽量な形。まずここで「検査可能な完了条件」を書く練習をする。

### Level 2: Builder と Judge の Subagent 連携

Builder役のsubagentとJudge役のsubagentを分離する(Agent tool で `subagent_type` を
分ける、または別セッションにする)。Judge には成果物とGround Truthだけを渡し、
**修正はさせない**。Judge の判定(PASS/FAIL/UNVERIFIED)を Manager(呼び出し元)が
受け取り、FAILならBuilderに差し戻す。

### Level 3: CLAUDE.md・Skill・Hookでの仕組み化

Level 2 の連携を毎回手で組まずに済むよう固定化する。

- **CLAUDE.md**: このループを使うべき場面・完了条件の書き方の規約を明記する。
- **Skill**: Builder/Judgeそれぞれの手順・チェック項目をSKILL.mdとしてテンプレ化する
  (このリポジトリの `extract-approach`, `shell-safety-check` が実例)。
- **Hook**: 特定のイベント(コミット前・セッション終了時など)で自動的にJudge相当の
  検査を走らせる。

## 安全運用ルール(交渉不可)

- **最大修正回数を設定する。** 上限に達したら PASS/FAIL によらず ESCALATE(人間に引き継ぐ)。
  無限ループを防ぐ。
- **FAIL箇所のみ修正する。** 全体再生成は、直っていた箇所まで壊す(退行)リスクがある。
- **リスクに応じて人間の最終確認を残す。** 全自動化を目的にしない。不可逆・影響範囲が
  広い成果物ほど、Judge PASS後も人間のレビューを挟む。
- **失敗が続く場合は人間に引き継ぐ。** Judgeが同じ理由でFAILを繰り返す、あるいは
  UNVERIFIEDが続くときは、Managerが自律的に判断を続けずESCALATEする。
- **Judgeの精度を事前にテストする。** 既知にPASS/FAILとわかっているサンプルをJudgeに
  流し、判定がぶれないか確認してから本番のループに組み込む。Judgeが間違えるループは
  害の方が大きい。

## 導入ロードマップ(4週間)

| 週 | やること |
|---|---|
| Week 1 | `/goal` で完了条件を明示する練習(Level 1)。 |
| Week 2 | Judge役を作る。Ground Truthの与え方と判定フォーマット(PASS/FAIL/UNVERIFIED)を決め、既知サンプルで精度をテストする。 |
| Week 3 | Builder役と接続し、Subagent連携(Level 2)を回す。最大修正回数・部分修正のルールを実際に効かせる。 |
| Week 4 | 定型化できたものをCLAUDE.md・Skill・Hookに落とす(Level 3)。 |

## 使うときの手順

1. 対象タスクの**完了条件をGround Truthとして書き出せるか**を最初に確認する
   (書けないタスクにはこのパターンを使わない)。
2. まず Level 1(`/goal`)で完了条件の書き方を検証する。
3. 繰り返し使うタスクなら Level 2 へ進め、Builder/JudgeをSubagentに分離する。
4. さらに定常化するなら Level 3 として CLAUDE.md・Skill・Hookに固定化する
   (このリポジトリなら `.claude/skills/` に新しいSKILL.mdを追加する形が実例)。
5. 上記「安全運用ルール」を全レベルで満たしているか確認する。

## 完了条件

- [ ] 対象タスクの完了条件(Ground Truth)が具体的に書けている。
- [ ] Builder役とJudge役の権限が分離されている(Judgeは編集しない)。
- [ ] 最大修正回数・部分修正・人間の最終確認・エスカレーション条件が決まっている。
- [ ] Judgeの判定精度を既知サンプルで確認した(Level 2以上の場合)。
- [ ] 定常運用にするなら、CLAUDE.md/Skill/Hookのどこに固定化するかが決まっている(Level 3の場合)。
