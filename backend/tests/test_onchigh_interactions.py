"""
Tests specifically for the ONCHigh-sourced interactions added to rules.py
(Phansalkar et al. 2012, JAMIA — see rules.py for the full citation).

These are separate from test_decision_engine.py's tests because they're
checking *content* (did the literature-sourced pairs get encoded
correctly) rather than the *mechanism* (does the matching logic work),
which the other file already covers thoroughly.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.data_access import DataSource, Event
from engine.decision_engine import check_drug_interactions
from engine import rules

NOW = datetime.now(timezone.utc)
SUBJECT = "test_subject"


class FakeDataSource(DataSource):
    def __init__(self, meds):
        self._meds = meds

    def get_meds(self, subject_id, since):
        return [e for e in self._meds if e.subject_id == subject_id and e.logged_at >= since]

    def get_vitals(self, subject_id, metric, since):
        return []

    def get_meals(self, subject_id, since):
        return []


def med(id_, name, is_supp=False):
    return Event(id_, SUBJECT, "cg1", NOW - timedelta(days=1), source="manual",
                 fields={"drug_name": name, "dose_mg": 1, "frequency": "daily", "is_supplement": is_supp})


def test_all_onchigh_entries_have_urgent_severity_and_citation():
    for entry in rules.ONCHIGH_INTERACTIONS:
        assert entry["severity"] == "urgent"
        assert "Phansalkar" in entry["clinical_note"]
        assert entry["drug_keywords"], f"{entry['rule_id']} has no drug_keywords"
        assert entry["conflict_keywords"], f"{entry['rule_id']} has no conflict_keywords"


def test_fourteen_onchigh_interactions_encoded():
    # 15 accepted by the panel, minus the 1 documented gap (QT-prolonging
    # agents x QT-prolonging agents, which needs an external member list)
    assert len(rules.ONCHIGH_INTERACTIONS) == 14


def test_ssri_plus_mao_inhibitor_triggers():
    ds = FakeDataSource([med("m1", "Sertraline 50mg"), med("m2", "Tranylcypromine 10mg")])
    findings = check_drug_interactions(ds, SUBJECT, NOW - timedelta(days=30))
    matched = [f for f in findings if f.rule_id == "onchigh_ddi_8"]
    assert len(matched) == 1
    assert matched[0].severity == "urgent"


def test_statin_plus_protease_inhibitor_triggers():
    ds = FakeDataSource([med("m1", "Simvastatin 40mg"), med("m2", "Ritonavir 100mg")])
    findings = check_drug_interactions(ds, SUBJECT, NOW - timedelta(days=30))
    matched = [f for f in findings if f.rule_id == "onchigh_ddi_25"]
    assert len(matched) == 1


def test_tizanidine_plus_ciprofloxacin_triggers():
    ds = FakeDataSource([med("m1", "Tizanidine 4mg"), med("m2", "Ciprofloxacin 500mg")])
    findings = check_drug_interactions(ds, SUBJECT, NOW - timedelta(days=30))
    matched = [f for f in findings if f.rule_id == "onchigh_ddi_28"]
    assert len(matched) == 1


def test_unrelated_drug_pair_does_not_trigger_onchigh_rules():
    ds = FakeDataSource([med("m1", "Paracetamol 500mg"), med("m2", "Metformin 500mg")])
    findings = check_drug_interactions(ds, SUBJECT, NOW - timedelta(days=30))
    onchigh_matches = [f for f in findings if f.rule_id.startswith("onchigh_")]
    assert onchigh_matches == []


def test_qt_prolonging_gap_is_documented_not_silently_missing():
    # This isn't testing behavior — it's a tripwire so nobody assumes DDI #21
    # exists just because the other 14 do. If someone adds it later without
    # updating this test, that's a deliberate, visible signal to update here too.
    rule_ids = {e["rule_id"] for e in rules.ONCHIGH_INTERACTIONS}
    assert "onchigh_ddi_21" not in rule_ids
