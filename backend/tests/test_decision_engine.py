"""
Unit tests for the decision engine. Each test builds a tiny synthetic
DataSource so the rule logic is verified against controlled inputs,
independent of the demo fixture in data/sample_events.json.

Run: pytest tests/ -v   (from the backend/ directory)
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.data_access import DataSource, Event
from engine.decision_engine import (
    check_drug_interactions, check_vitals, check_meal_gaps, run_all_rules,
)

NOW = datetime.now(timezone.utc)
SUBJECT = "test_subject"


class FakeDataSource(DataSource):
    """In-memory DataSource for precise, controlled test scenarios."""
    def __init__(self, meds=None, vitals=None, meals=None):
        self._meds = meds or []
        self._vitals = vitals or []
        self._meals = meals or []

    def get_meds(self, subject_id, since):
        return [e for e in self._meds if e.subject_id == subject_id and e.logged_at >= since]

    def get_vitals(self, subject_id, metric, since):
        return sorted(
            [e for e in self._vitals if e.subject_id == subject_id
             and e.fields["metric"] == metric and e.logged_at >= since],
            key=lambda e: e.logged_at,
        )

    def get_meals(self, subject_id, since):
        return [e for e in self._meals if e.subject_id == subject_id and e.logged_at >= since]


def med_event(id_, name, is_supp, days_ago=1):
    return Event(id_, SUBJECT, "cg1", NOW - timedelta(days=days_ago),
                 source="manual", fields={"drug_name": name, "dose_mg": 50,
                                           "frequency": "daily", "is_supplement": is_supp})


def vital_event(id_, metric, value, days_ago=0):
    return Event(id_, SUBJECT, "cg1", NOW - timedelta(days=days_ago),
                 source="manual", fields={"metric": metric, "value": value, "unit": "mmHg"})


def meal_event(id_, status, days_ago=1):
    return Event(id_, SUBJECT, "cg1", NOW - timedelta(days=days_ago),
                 source="manual", fields={"meal": "lunch", "status": status, "note": None})


# ---------------------------------------------------------------------------
# Rule 1 — drug interactions
# ---------------------------------------------------------------------------
def test_drug_interaction_triggers_when_both_present():
    ds = FakeDataSource(meds=[
        med_event("m1", "Losartan 50mg", is_supp=False),
        med_event("m2", "Potassium 99mg", is_supp=True),
    ])
    findings = check_drug_interactions(ds, SUBJECT, NOW - timedelta(days=30))
    assert len(findings) == 1
    assert findings[0].severity == "urgent"
    assert findings[0].rule_id == "drug_supplement_interaction"
    assert len(findings[0].trace) == 2


def test_drug_interaction_silent_when_only_one_drug_present():
    ds = FakeDataSource(meds=[med_event("m1", "Losartan 50mg", is_supp=False)])
    findings = check_drug_interactions(ds, SUBJECT, NOW - timedelta(days=30))
    assert findings == []


def test_drug_interaction_silent_for_unrelated_drugs():
    ds = FakeDataSource(meds=[
        med_event("m1", "Paracetamol 500mg", is_supp=False),
        med_event("m2", "Vitamin C", is_supp=True),
    ])
    findings = check_drug_interactions(ds, SUBJECT, NOW - timedelta(days=30))
    assert findings == []


# ---------------------------------------------------------------------------
# Rule 2 — vitals threshold + trend
# ---------------------------------------------------------------------------
def test_vitals_single_reading_urgent_above_160():
    ds = FakeDataSource(vitals=[vital_event("v1", "bp_systolic", 165, days_ago=0)])
    findings = check_vitals(ds, SUBJECT, NOW - timedelta(days=30))
    urgent = [f for f in findings if f.rule_id == "vitals_single_threshold"]
    assert len(urgent) == 1
    assert urgent[0].severity == "urgent"


def test_vitals_single_reading_watch_between_150_and_160():
    ds = FakeDataSource(vitals=[vital_event("v1", "bp_systolic", 152, days_ago=0)])
    findings = check_vitals(ds, SUBJECT, NOW - timedelta(days=30))
    watch = [f for f in findings if f.rule_id == "vitals_single_threshold"]
    assert len(watch) == 1
    assert watch[0].severity == "watch"


def test_vitals_below_threshold_no_finding():
    ds = FakeDataSource(vitals=[vital_event("v1", "bp_systolic", 130, days_ago=0)])
    findings = check_vitals(ds, SUBJECT, NOW - timedelta(days=30))
    assert findings == []


def test_vitals_trend_triggers_on_sustained_rise():
    readings = [vital_event(f"v{i}", "bp_systolic", 125 + i * 4, days_ago=6 - i) for i in range(6)]
    ds = FakeDataSource(vitals=readings)
    findings = check_vitals(ds, SUBJECT, NOW - timedelta(days=30))
    trend = [f for f in findings if f.rule_id == "vitals_trend"]
    assert len(trend) == 1
    assert trend[0].severity == "watch"


def test_vitals_trend_silent_when_flat():
    readings = [vital_event(f"v{i}", "bp_systolic", 128 + (i % 2), days_ago=6 - i) for i in range(6)]
    ds = FakeDataSource(vitals=readings)
    findings = check_vitals(ds, SUBJECT, NOW - timedelta(days=30))
    trend = [f for f in findings if f.rule_id == "vitals_trend"]
    assert trend == []


# ---------------------------------------------------------------------------
# Rule 3 — meal gaps
# ---------------------------------------------------------------------------
def test_meal_gap_triggers_at_two_skips():
    ds = FakeDataSource(meals=[
        meal_event("me1", "skipped", days_ago=4),
        meal_event("me2", "skipped", days_ago=2),
        meal_event("me3", "eaten", days_ago=1),
    ])
    findings = check_meal_gaps(ds, SUBJECT, NOW - timedelta(days=30))
    assert len(findings) == 1
    assert findings[0].severity == "monitor"


def test_meal_gap_silent_below_threshold():
    ds = FakeDataSource(meals=[
        meal_event("me1", "skipped", days_ago=4),
        meal_event("me2", "eaten", days_ago=1),
    ])
    findings = check_meal_gaps(ds, SUBJECT, NOW - timedelta(days=30))
    assert findings == []


# ---------------------------------------------------------------------------
# Integration — run_all_rules sorts by severity and reports latency
# ---------------------------------------------------------------------------
def test_run_all_rules_sorts_by_severity_and_measures_latency():
    ds = FakeDataSource(
        meds=[med_event("m1", "Losartan", is_supp=False), med_event("m2", "Potassium", is_supp=True)],
        vitals=[vital_event("v1", "bp_systolic", 152, days_ago=0)],
        meals=[meal_event("me1", "skipped", 4), meal_event("me2", "skipped", 2)],
    )
    findings, latency_ms = run_all_rules(ds, SUBJECT, lookback_days=30)
    severities = [f.severity for f in findings]
    assert severities == sorted(severities, key=lambda s: {"urgent": 0, "watch": 1, "monitor": 2}[s])
    assert latency_ms >= 0
    assert len(findings) == 3
