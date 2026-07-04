"""
Tests for engine/openfda_client.py and the check_openfda_crossref rule.

No real network call is made anywhere in this file — the HTTP layer is
mocked with unittest.mock. This is deliberate: the sandbox this project
was built in has no egress to api.fda.gov, and even outside that sandbox,
unit tests that depend on a live third-party API are flaky by nature.
The mocked JSON shape matches openFDA's documented response format
(https://open.fda.gov/apis/drug/label/) — field names and nesting were
verified against openFDA's own docs and a working example query, not
guessed.

scripts/smoke_test_openfda.py (see README) is the separate, explicitly
non-automated script for confirming live behaviour against the real API.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.openfda_client import OpenFDAClient, DrugLabel, label_mentions_drug
from engine.data_access import DataSource, Event
from engine.decision_engine import check_openfda_crossref

NOW = datetime.now(timezone.utc)
SUBJECT = "test_subject"


def fake_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.url = "https://api.fda.gov/drug/label.json?search=openfda.generic_name:%22losartan%22"
    return resp


LOSARTAN_LABEL_JSON = {
    "results": [{
        "drug_interactions": [
            "Potassium: Losartan may increase serum potassium levels, especially "
            "when used with potassium supplements or potassium-sparing diuretics."
        ],
        "warnings": ["Monitor renal function periodically."],
        "contraindications": [],
        "openfda": {"spl_set_id": ["abc-123-def"], "generic_name": ["LOSARTAN POTASSIUM"]},
    }]
}


# ---------------------------------------------------------------------------
# OpenFDAClient
# ---------------------------------------------------------------------------
def test_get_label_parses_successful_response():
    session = MagicMock()
    session.get.return_value = fake_response(200, LOSARTAN_LABEL_JSON)
    client = OpenFDAClient(session=session)

    label = client.get_label("losartan")

    assert label is not None
    assert "potassium" in label.drug_interactions_text.lower()
    assert label.spl_set_id == "abc-123-def"
    session.get.assert_called_once()


def test_get_label_returns_none_on_empty_results():
    session = MagicMock()
    session.get.return_value = fake_response(200, {"results": []})
    client = OpenFDAClient(session=session)

    assert client.get_label("not_a_real_drug") is None


def test_get_label_returns_none_on_http_error():
    session = MagicMock()
    session.get.return_value = fake_response(404, {})
    client = OpenFDAClient(session=session)

    assert client.get_label("losartan") is None


def test_get_label_returns_none_on_network_exception():
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("no network in this sandbox")
    client = OpenFDAClient(session=session)

    # must not raise — this is the behaviour the whole pipeline depends on
    assert client.get_label("losartan") is None


def test_get_label_is_cached_within_ttl():
    session = MagicMock()
    session.get.return_value = fake_response(200, LOSARTAN_LABEL_JSON)
    client = OpenFDAClient(session=session)

    client.get_label("losartan")
    client.get_label("losartan")
    client.get_label("LOSARTAN")  # case-insensitive cache key

    assert session.get.call_count == 1


def test_label_mentions_drug_matches_case_insensitively():
    label = DrugLabel("losartan", "May interact with Potassium supplements.", "", "", None, "")
    assert label_mentions_drug(label, "potassium") is True
    assert label_mentions_drug(label, "POTASSIUM") is True
    assert label_mentions_drug(label, "ibuprofen") is False


# ---------------------------------------------------------------------------
# check_openfda_crossref (using a fake DataSource + mocked client)
# ---------------------------------------------------------------------------
class FakeDataSource(DataSource):
    def __init__(self, meds):
        self._meds = meds

    def get_meds(self, subject_id, since):
        return [e for e in self._meds if e.subject_id == subject_id and e.logged_at >= since]

    def get_vitals(self, subject_id, metric, since):
        return []

    def get_meals(self, subject_id, since):
        return []


def med_event(id_, name):
    return Event(id_, SUBJECT, "cg1", NOW - timedelta(days=1), source="manual",
                 fields={"drug_name": name, "dose_mg": 50, "frequency": "daily", "is_supplement": False})


def test_crossref_finds_mention_and_caps_severity_at_watch():
    ds = FakeDataSource(meds=[
        med_event("m1", "Losartan 50mg"),
        med_event("m2", "Potassium 99mg"),
    ])
    session = MagicMock()
    session.get.return_value = fake_response(200, LOSARTAN_LABEL_JSON)
    client = OpenFDAClient(session=session)

    findings = check_openfda_crossref(ds, SUBJECT, NOW - timedelta(days=30), client=client)

    assert len(findings) == 1
    assert findings[0].severity == "watch"          # never "urgent" — see openfda_client.py
    assert findings[0].rule_id == "openfda_label_crossref"
    assert len(findings[0].trace) == 2
    assert "source_url" in findings[0].facts


def test_crossref_silent_when_label_unreachable():
    ds = FakeDataSource(meds=[med_event("m1", "Losartan 50mg"), med_event("m2", "Potassium 99mg")])
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("offline")
    client = OpenFDAClient(session=session)

    findings = check_openfda_crossref(ds, SUBJECT, NOW - timedelta(days=30), client=client)

    assert findings == []  # degrades to nothing, does not raise


def test_crossref_silent_with_fewer_than_two_meds():
    ds = FakeDataSource(meds=[med_event("m1", "Losartan 50mg")])
    findings = check_openfda_crossref(ds, SUBJECT, NOW - timedelta(days=30), client=MagicMock())
    assert findings == []
