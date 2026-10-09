"""BigQuery への書き込み・読み出し。

書き込みは「ステージングへロード → MERGE」で行い、同じ期間を何度取り直しても重複しない(冪等)。
google-cloud-bigquery は重いので、この関数を呼ぶときだけ import する。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SA_ENV = "BQ_SERVICE_ACCOUNT_JSON"
_SA_KEYS = ("type", "project_id", "private_key", "client_email", "token_uri")

SQL_DIR = Path(__file__).resolve().parents[3] / "sql"


def service_account_info(env: dict | None = None) -> dict | None:
    """環境変数 BQ_SERVICE_ACCOUNT_JSON(サービスアカウント鍵のJSON本文)を検証して返す。無ければ None。

    コネクタ(OAuth)は期限切れで外れるが、サービスアカウントは外れない。鍵の中身はエラー文にも出さない。
    """
    raw = (env if env is not None else os.environ).get(SA_ENV, "").strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except ValueError:
        raise ValueError(f"{SA_ENV} が JSON として読めません(鍵ファイルの中身をそのまま貼る)") from None
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ValueError(f"{SA_ENV} がサービスアカウント鍵ではありません(type=service_account が必要)")
    missing = [k for k in _SA_KEYS if not info.get(k)]
    if missing:
        raise ValueError(f"{SA_ENV} に必須キーがありません: {', '.join(missing)}")
    return info


def client(project: str):
    from google.cloud import bigquery

    info = service_account_info()
    if info is None:
        return bigquery.Client(project=project)  # 従来どおり ADC
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=project, credentials=creds)


def apply_sql_file(project: str, dataset: str, filename: str) -> None:
    """sql/ 配下の DDL/ビュー定義を実行する。${dataset} をデータセット名に置換。"""
    sql = (SQL_DIR / filename).read_text(encoding="utf-8").replace("${dataset}", f"{project}.{dataset}")
    bq = client(project)
    for stmt in [s.strip() for s in sql.split(";\n") if s.strip()]:
        bq.query(stmt).result()


def upsert_ad_daily(project: str, dataset: str, rows: list[dict], since: str, until: str, account_id: str) -> int:
    """raw_ad_daily の [since, until] × account_id を rows で置き換える。

    MERGE ではなく「期間削除 → 挿入」をトランザクション内で行う。API 側で広告が削除されて
    行が消えたケースも正しく反映するため(MERGE だと古い行が残る)。
    """
    from google.cloud import bigquery

    if not rows:
        # 0行のときは既存データを消さない(配信停止か取得異常かをここでは区別できないため、壊れない側に倒す)
        return 0
    bq = client(project)
    table = f"{project}.{dataset}.raw_ad_daily"
    staging = f"{project}.{dataset}._stg_ad_daily"
    job = bq.load_table_from_json(
        rows,
        staging,
        job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE",
            schema=bq.get_table(table).schema,
        ),
    )
    job.result()
    bq.query(
        f"""
        BEGIN TRANSACTION;
        DELETE FROM `{table}`
          WHERE date BETWEEN @since AND @until AND account_id = @account_id;
        INSERT INTO `{table}` SELECT * FROM `{staging}`;
        COMMIT TRANSACTION;
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("since", "DATE", since),
                bigquery.ScalarQueryParameter("until", "DATE", until),
                bigquery.ScalarQueryParameter("account_id", "STRING", account_id),
            ]
        ),
    ).result()
    return len(rows)


def query(project: str, sql: str, params: dict | None = None) -> list[dict]:
    from google.cloud import bigquery

    qp = []
    for k, v in (params or {}).items():
        typ = "FLOAT64" if isinstance(v, float) else "INT64" if isinstance(v, int) else "STRING"
        qp.append(bigquery.ScalarQueryParameter(k, typ, v))
    rows = client(project).query(sql, job_config=bigquery.QueryJobConfig(query_parameters=qp)).result()
    return [dict(r) for r in rows]


def insert_rows(project: str, dataset: str, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    errors = client(project).insert_rows_json(f"{project}.{dataset}.{table}", rows)
    if errors:
        raise RuntimeError(f"{table} への挿入に失敗: {errors[:3]}")
