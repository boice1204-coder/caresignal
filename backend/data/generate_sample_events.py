"""
Generates data/sample_events.json — fixture data for the "Tan Ah Hoon"
demo scenario (the same subject used in the wireframe), with timestamps
relative to *now* so the trend/threshold/meal-gap rules trigger correctly
no matter when this is run.

Run: python3 generate_sample_events.py
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

now = datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


SUBJECT_ID = "subj_tan_ah_hoon"
CAREGIVER_ASTRID = "cg_astrid"
CAREGIVER_WEIMING = "cg_weiming"

meds_log = [
    # supplement, logged months ago (recurring)
    {
        "event_id": "med_001", "subject_id": SUBJECT_ID, "caregiver_id": CAREGIVER_WEIMING,
        "drug_name": "Potassium 99mg", "dose_mg": 99, "frequency": "daily",
        "is_supplement": True, "source": "manual",
        "logged_at": iso(now - timedelta(days=110)),
    },
    # new prescription, logged 2 days ago -> should trigger urgent interaction finding
    {
        "event_id": "med_002", "subject_id": SUBJECT_ID, "caregiver_id": CAREGIVER_ASTRID,
        "drug_name": "Losartan 50mg", "dose_mg": 50, "frequency": "daily",
        "is_supplement": False, "source": "ocr_receipt",
        "logged_at": iso(now - timedelta(days=2, hours=3)),
    },
]

# 7 days of rising systolic readings -> should trigger the trend rule
vitals_log = []
base_systolic = 128
for i, days_ago in enumerate([6, 5, 4, 3, 2, 1, 0]):
    vitals_log.append({
        "event_id": f"vit_sys_{i:03d}", "subject_id": SUBJECT_ID, "caregiver_id": CAREGIVER_ASTRID,
        "metric": "bp_systolic", "value": base_systolic + i * 3.5, "unit": "mmHg",
        "source": "ble_monitor",
        "logged_at": iso(now - timedelta(days=days_ago, hours=8)),
    })
vitals_log.append({
    "event_id": "vit_dia_000", "subject_id": SUBJECT_ID, "caregiver_id": CAREGIVER_ASTRID,
    "metric": "bp_diastolic", "value": 82, "unit": "mmHg", "source": "ble_monitor",
    "logged_at": iso(now - timedelta(hours=8)),
})

# 2 skipped lunches this week -> should trigger the meal-gap rule
meal_log = [
    {
        "event_id": "meal_001", "subject_id": SUBJECT_ID, "caregiver_id": CAREGIVER_ASTRID,
        "meal": "lunch", "status": "skipped", "note": "Wasn't hungry",
        "logged_at": iso(now - timedelta(days=4)),
    },
    {
        "event_id": "meal_002", "subject_id": SUBJECT_ID, "caregiver_id": CAREGIVER_ASTRID,
        "meal": "lunch", "status": "skipped", "note": "Napped through it",
        "logged_at": iso(now - timedelta(days=2)),
    },
    {
        "event_id": "meal_003", "subject_id": SUBJECT_ID, "caregiver_id": CAREGIVER_WEIMING,
        "meal": "dinner", "status": "eaten", "note": None,
        "logged_at": iso(now - timedelta(days=1)),
    },
]

fixture = {"meds_log": meds_log, "vitals_log": vitals_log, "meal_log": meal_log}

out_path = Path(__file__).parent / "sample_events.json"
out_path.write_text(json.dumps(fixture, indent=2))
print(f"wrote {out_path} ({len(meds_log)} meds, {len(vitals_log)} vitals, {len(meal_log)} meals)")
