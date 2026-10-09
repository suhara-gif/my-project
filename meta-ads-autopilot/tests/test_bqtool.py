import json

import pytest

from meta_autopilot.bqtool import MECHANIC_DEF, validate_rows
from meta_autopilot.ingest.bq import SA_ENV, service_account_info

GOOD = {
    "type": "service_account",
    "project_id": "p",
    "private_key": "-----BEGIN PRIVATE KEY-----SECRET",
    "client_email": "x@p.iam.gserviceaccount.com",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def test_no_env_means_adc():
    assert service_account_info({}) is None
    assert service_account_info({SA_ENV: "  "}) is None


def test_valid_key_is_parsed():
    assert service_account_info({SA_ENV: json.dumps(GOOD)})["client_email"] == GOOD["client_email"]


@pytest.mark.parametrize(
    "raw",
    ["not json SECRET", json.dumps({**GOOD, "type": "authorized_user"}), json.dumps({k: v for k, v in GOOD.items() if k != "private_key"})],
)
def test_bad_key_is_rejected_without_leaking(raw):
    with pytest.raises(ValueError) as e:
        service_account_info({SA_ENV: raw})
    assert "SECRET" not in str(e.value)


def _row(**kw):
    r = {"date": "2026-10-03", "ad_id": "1", "spend": 100, "impressions": 10, "cv": 0, "cv_definition": "omni_complete_registration"}
    r.update(kw)
    return r


def test_validate_ok_and_sets_account():
    rows = [_row(), _row(cv=None, cv_definition=MECHANIC_DEF)]
    validate_rows(rows, "A", "2026-10-02", "2026-10-08")
    assert all(r["account_id"] == "A" for r in rows)


@pytest.mark.parametrize(
    "rows",
    [[], [_row(cv=None)], [_row(date="2026-09-01")], [{"date": "2026-10-03"}], [_row(account_id="B")]],
)
def test_validate_rejects(rows):
    with pytest.raises(ValueError):
        validate_rows(rows, "A", "2026-10-02", "2026-10-08")
