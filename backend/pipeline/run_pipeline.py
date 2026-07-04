"""
End-to-end pipeline: ingest -> score -> explain -> alert.

This is the local runnable version of what Vertex AI Pipelines orchestrates
in production (see sql/schema.sql + README.md for the mapping). Swapping
LocalDataSource for BigQueryDataSource is the only change needed to point
this at a real GCP project — the decision engine and explainer are already
data-source-agnostic.

Run: python3 run_pipeline.py
"""
import sys
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.data_access import LocalDataSource
from engine.decision_engine import run_all_rules
from engine.gemini_explainer import explain

FIXTURE_PATH = Path(__file__).parent.parent / "data" / "sample_events.json"
SUBJECT_ID = "subj_tan_ah_hoon"


def alert_severity_rank(sev):
    return {"urgent": 0, "watch": 1, "monitor": 2}.get(sev, 9)


def main():
    ds = LocalDataSource(str(FIXTURE_PATH))

    findings, latency_ms = run_all_rules(ds, SUBJECT_ID, lookback_days=120)

    alerts = []
    for f in findings:
        copy = explain(f)
        alerts.append({
            "alert_id": str(uuid.uuid4()),
            "subject_id": f.subject_id,
            "rule_id": f.rule_id,
            "rule_label": f.rule_label,
            "severity": f.severity,
            "title": copy["title"],
            "body": copy["body"],
            "suggested_action": copy["suggested_action"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "trace": [
                {
                    "source_table": t.source_table,
                    "source_event_id": t.source_event_id,
                    "label": t.label,
                    "detail": t.detail,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in f.trace
            ],
        })

    print(f"\nScored {SUBJECT_ID} against all rules in {latency_ms} ms.")
    print(f"Manual cross-check of the same data typically takes 15-30 minutes.\n")
    print(f"Found {len(alerts)} alert(s):\n")
    for a in alerts:
        print(f"  [{a['severity'].upper():8s}] {a['title']}")
        print(f"             rule: {a['rule_label']}")
        print(f"             action: {a['suggested_action']}")
        print()

    out_path = Path(__file__).parent.parent / "data" / "pipeline_output.json"
    out_path.write_text(json.dumps({
        "subject_id": SUBJECT_ID,
        "scoring_latency_ms": latency_ms,
        "alerts": alerts,
    }, indent=2))
    print(f"Full alert payload (matches the wireframe's data shape) written to {out_path}")


if __name__ == "__main__":
    main()
