# Meta広告のキャンペーン成果をSalesforceの「整備士」と突合する方法(トヨワク)

- 日付: 2026-09-25
- 種別: 調査
- 触れたファイル: company/knowledge/business.md

## 問題
トヨワク(Meta広告アカウント 1280868240318718)のキャンペーン別成果が、実際に整備士の獲得につながっているかを
Salesforce(SF)の求職者データと突合して確かめる必要があった。

## 文脈
- SFの `Contact` には **MetaのキャンペーンID・広告セットIDを持つ項目が無い**。TW向けに `media_ad_type_tw__c` はあるが
  中身はGoogleの SEARCH / PERFORMANCE_MAX / DEMAND_GEN だけで、Meta流入では空。
- 整備士を表しそうな項目が複数ある。`Field58__c`(整備資格抽出, boolean)は直近30日のTW流入でほぼ全件 false。
- Metaの「成果」はピクセルの `complete_registration`(サイト登録完了)。SF流入数とは定義が違う。

## 解法と、その理由
1. TW流入は `ManagementToyowakuInflowDate_del__c`(【管理】トヨワク流入日)、Meta由来は
   `sourceMedium_j_tw__c = 'meta / cpc'` で絞り込む。
2. 整備士フラグは `Field63__c`(整備士判定（カーワク）, 値は「整備士」/「その他」)を使う。レコードを抜き出して見ると、
   希望職種が「整備士/エンジニア」のレコードと概ね一致し、`Field58__c` よりはるかに実態に近かった。
   数式項目のため GROUP BY はできない。`WHERE Field63__c = '整備士'` を付けて COUNT する。
3. ~~キャンペーン別の内訳はSFでは取れない~~ → **取れる(2026-09-28 訂正)**。`Contact` 本体には無いが、子オブジェクト
   `ContactExtended_JS__c`(求職者拡張情報、`Contact__c` で主従)に `media_ad_campaign_tw__c`
   (【メディア】広告キャンペーン名（トヨワク）)がある。カーワク・メカワク・シニア用に `_cw` `_mw` `_sr` もある。
   ```
   SELECT media_ad_campaign_tw__c, Contact__r.ManagementToyowakuInflowDate_del__c,
          Contact__r.sourceMedium_j_tw__c, Contact__r.Field63__c
   FROM ContactExtended_JS__c
   WHERE Contact__r.ManagementToyowakuInflowDate_del__c >= 2026-08-01 AND ... <= 2026-09-27
   ```
   Field63__c は数式なので GROUP BY できない。行を取ってローカルで集計する。
   値の形の注意: Meta の ASC は「広告セット名-配信面」(例 `トヨワクASC1-fb`, `整備士狙い_ASC-ig`)、
   AI動画キャンペーンは**名前ではなくキャンペーンID**(`120252286258710028`)で入っていた。
   (当初は期間で区切る推定で代替したが、実数で出すと推定と同じ「AI動画19人中整備士1人」だった。)

## うまくいかなかったこと
- `Field58__c` を整備士フラグに使うと、整備士が0件という誤った結論になる。
- `GROUP BY Field63__c` はエラー(`can not be grouped`)になる。

## 抽出したルール / ヒューリスティック
- SFで整備士を数えるときは `Field63__c = '整備士'` を使う。使う前に、希望職種など別の項目とレコード単位で一致するか
  数件だけ見て確かめる。項目の名前だけを見て選ばない。
- Metaの登録完了数をそのまま「応募」とみなさない。必ずSF流入数と並べて書く(平常時でも1.3〜1.9倍の差がある)。
- キャンペーン別の内訳が「SFに無い」と判断する前に、Contact 本体だけでなく子オブジェクト
  (特に `ContactExtended_JS__c`)の項目も確認する。レポートタイプ名に「拡張項目」とあれば子オブジェクトを疑う。
- 項目の検索はAPI名の LIKE だけでは漏れる。オブジェクト一覧(getObjectSchema の index)から候補を当たる。

## 関連
- [20260817-promote-only-after-listing-assumptions.md](20260817-promote-only-after-listing-assumptions.md)
