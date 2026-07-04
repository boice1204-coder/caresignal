"""
CareSignal decision engine.

This is the piece the pitch calls "core IP": deterministic, auditable
clinical logic that produces a risk finding *with its exact evidence
trail*. Gemini (see gemini_explainer.py) is only allowed to translate a
finding into plain language after the fact — it never decides whether a
risk exists. That split is what keeps every alert explainable.

Each check_* function is independently unit-testable (see tests/) and
returns zero or more RiskFinding objects. run_all_rules() is the entry
point the pipeline calls, and it also measures wall-clock latency so the
"under 5 seconds" acceleration claim is a number we actually produced,
not a guess.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
import time

from .data_access import DataSource, Event
from . import rules
from .openfda_client import OpenFDAClient, label_mentions_drug


@dataclass
class TraceItem:
    source_table: str
    source_event_id: str
    label: str
    detail: str
    timestamp: datetime


@dataclass
class RiskFinding:
    subject_id: str
    rule_id: str
    rule_label: str
    severity: str                 # 'urgent' | 'watch' | 'monitor'
    facts: dict = field(default_factory=dict)   # structured facts for the Gemini explainer
    trace: list[TraceItem] = field(default_factory=list)
    score: float = 0.0


# ---------------------------------------------------------------------------
# Rule 1 — drug / supplement interaction
# ---------------------------------------------------------------------------
def check_drug_interactions(ds: DataSource, subject_id: str, since: datetime) -> list[RiskFinding]:
    meds = ds.get_meds(subject_id, since)
    if not meds:
        return []

    findings = []
    for interaction in rules.DRUG_INTERACTIONS:
        drug_events = [
            m for m in meds
            if not m.fields.get("is_supplement")
            and any(k in str(m.fields.get("drug_name", "")).lower() for k in interaction["drug_keywords"])
        ]
        conflict_events = [
            m for m in meds
            if any(k in str(m.fields.get("drug_name", "")).lower() for k in interaction["conflict_keywords"])
        ]
        if drug_events and conflict_events:
            drug = max(drug_events, key=lambda e: e.logged_at)     # most recent prescription
            conflict = max(conflict_events, key=lambda e: e.logged_at)
            findings.append(RiskFinding(
                subject_id=subject_id,
                rule_id=interaction["rule_id"],
                rule_label=f"{drug.fields['drug_name']} + {conflict.fields['drug_name']} interaction check",
                severity=interaction["severity"],
                facts={
                    "drug_name": drug.fields["drug_name"],
                    "conflict_name": conflict.fields["drug_name"],
                    "clinical_note": interaction["clinical_note"],
                },
                trace=[
                    TraceItem("meds_log", drug.event_id,
                              f"Prescription logged — {drug.fields['drug_name']}",
                              f"{drug.fields.get('dose_mg', '?')}mg · source: {drug.source}",
                              drug.logged_at),
                    TraceItem("meds_log", conflict.event_id,
                              f"Supplement logged — {conflict.fields['drug_name']}",
                              f"{conflict.fields.get('frequency', '')} · source: {conflict.source}",
                              conflict.logged_at),
                ],
                score=0.95,
            ))
    return findings


# ---------------------------------------------------------------------------
# Rule 1b — openFDA label cross-reference (augments, never replaces, the
# curated table above; see engine/openfda_client.py for the reasoning)
# ---------------------------------------------------------------------------
def check_openfda_crossref(
    ds: DataSource, subject_id: str, since: datetime, client: Optional[OpenFDAClient] = None
) -> list[RiskFinding]:
    meds = ds.get_meds(subject_id, since)
    if len(meds) < 2:
        return []
    client = client or OpenFDAClient()

    findings = []
    seen_pairs = set()
    for drug in meds:
        raw_name = str(drug.fields.get("drug_name", ""))
        if not raw_name:
            continue
        name = raw_name.split()[0]  # strip dose, e.g. "Losartan 50mg" -> "Losartan", *before* any use
        label = client.get_label(name)
        if label is None:
            continue
        for other in meds:
            if other.event_id == drug.event_id:
                continue
            other_name = str(other.fields.get("drug_name", "")).split()[0]
            if not other_name:
                continue
            pair_key = tuple(sorted([name.lower(), other_name.lower()]))
            if pair_key in seen_pairs:
                continue
            if label_mentions_drug(label, other_name):
                seen_pairs.add(pair_key)
                findings.append(RiskFinding(
                    subject_id=subject_id,
                    rule_id="openfda_label_crossref",
                    rule_label=f"openFDA label cross-reference \u2014 {raw_name} label mentions {other_name}",
                    severity="watch",  # capped below "urgent" \u2014 see openfda_client.py docstring
                    facts={
                        "drug_name": raw_name, "mentioned_drug": other_name,
                        "source_url": label.source_url,
                    },
                    trace=[
                        TraceItem("meds_log", drug.event_id, f"Prescription logged \u2014 {raw_name}",
                                  f"source: {drug.source}", drug.logged_at),
                        TraceItem("openfda_label", label.spl_set_id or "unknown",
                                  f"FDA label for {name} mentions \u201c{other_name}\u201d",
                                  f"openFDA drug_interactions section \u00b7 {label.source_url}",
                                  drug.logged_at),
                    ],
                    score=0.4,
                ))
    return findings


# ---------------------------------------------------------------------------
# Rule 2 — vitals threshold + trend
# ---------------------------------------------------------------------------
def check_vitals(ds: DataSource, subject_id: str, since: datetime) -> list[RiskFinding]:
    findings = []
    for threshold in rules.VITALS_THRESHOLDS:
        readings = ds.get_vitals(subject_id, threshold.metric, since)
        if not readings:
            continue

        # --- single-reading threshold check ---
        latest = readings[-1]
        val = float(latest.fields["value"])
        crossed = val >= threshold.urgent_at or val >= threshold.watch_at
        if crossed:
            severity = "urgent" if val >= threshold.urgent_at else "watch"
            findings.append(RiskFinding(
                subject_id=subject_id,
                rule_id="vitals_single_threshold",
                rule_label=f"Single-reading threshold check — {threshold.metric} \u2265 {threshold.watch_at}",
                severity=severity,
                facts={"metric": threshold.metric, "value": val, "threshold": threshold.watch_at},
                trace=[TraceItem("vitals_log", latest.event_id,
                                  f"Vitals logged — {threshold.metric} {val}",
                                  f"source: {latest.source}", latest.logged_at)],
                score=0.8 if severity == "urgent" else 0.55,
            ))
            continue  # don't double-report the same metric via the trend check

        # --- rolling trend check ---
        window_start = datetime.now(readings[-1].logged_at.tzinfo) - timedelta(days=rules.TREND_WINDOW_DAYS)
        window = [r for r in readings if r.logged_at >= window_start]
        if len(window) >= rules.TREND_MIN_READINGS:
            rise = float(window[-1].fields["value"]) - float(window[0].fields["value"])
            if rise >= rules.TREND_RISE_WATCH:
                findings.append(RiskFinding(
                    subject_id=subject_id,
                    rule_id="vitals_trend",
                    rule_label=f"{rules.TREND_WINDOW_DAYS}-day rolling trend — {threshold.metric} slope check",
                    severity="watch",
                    facts={"metric": threshold.metric, "rise": rise, "readings": len(window)},
                    trace=[TraceItem("vitals_log", "range", f"Vitals logged — {len(window)} readings",
                                      f"{window[0].logged_at.date()} \u2013 {window[-1].logged_at.date()}",
                                      window[-1].logged_at)],
                    score=0.5,
                ))
    return findings


# ---------------------------------------------------------------------------
# Rule 3 — meal-logging gap
# ---------------------------------------------------------------------------
def check_meal_gaps(ds: DataSource, subject_id: str, since: datetime) -> list[RiskFinding]:
    meals = ds.get_meals(subject_id, since)
    window_start = datetime.now(meals[0].logged_at.tzinfo) - timedelta(days=rules.MEAL_GAP_WINDOW_DAYS) if meals else since
    skipped = [m for m in meals if m.fields.get("status") == "skipped" and m.logged_at >= window_start]
    if len(skipped) >= rules.MEAL_GAP_MIN_SKIPS:
        return [RiskFinding(
            subject_id=subject_id,
            rule_id="meal_logging_gap",
            rule_label=f"Meal-logging gap check — {rules.MEAL_GAP_MIN_SKIPS}+ misses in {rules.MEAL_GAP_WINDOW_DAYS} days",
            severity="monitor",
            facts={"skipped_count": len(skipped)},
            trace=[TraceItem("meal_log", m.event_id, f"Meal note logged — \u201cSkipped {m.fields.get('meal')}\u201d",
                              f"{m.logged_at.date()} \u00b7 added by {m.caregiver_id}", m.logged_at)
                   for m in skipped],
            score=0.3,
        )]
    return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
SEVERITY_ORDER = {"urgent": 0, "watch": 1, "monitor": 2}


def run_all_rules(
    ds: DataSource, subject_id: str, lookback_days: int = 90, include_openfda: bool = False
) -> tuple[list[RiskFinding], int]:
    """Runs every rule and returns (findings sorted by severity, latency_ms).

    latency_ms only covers the scoring step (ingestion is assumed already
    complete) — it's the number that backs the "under 5 seconds" claim on
    slide 6, and it's produced by actually running the code, not asserted.

    include_openfda defaults to False: it makes a real network call per
    unique drug, which (a) needs internet access and (b) makes the latency
    number no longer purely a reflection of the local decision engine.
    Turn it on deliberately (e.g. for a "look, it's checking the live FDA
    database right now" demo moment), not for the core speed claim.
    """
    t0 = time.perf_counter()
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    findings: list[RiskFinding] = []
    findings += check_drug_interactions(ds, subject_id, since)
    findings += check_vitals(ds, subject_id, since)
    findings += check_meal_gaps(ds, subject_id, since)
    if include_openfda:
        findings += check_openfda_crossref(ds, subject_id, since)

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), -f.score))
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return findings, latency_ms
