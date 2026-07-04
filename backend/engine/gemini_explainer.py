"""
Explanation layer — turns a RiskFinding into the plain-language alert
copy the caregiver actually reads (matches the wireframe's alert-card /
alert-detail fields exactly: title, body, suggested_action).

This is intentionally the *only* place Gemini touches the pipeline.
It receives a finding that has already been decided (rule id, severity,
structured facts, evidence trail) and is only asked to phrase it —
never to judge whether it's risky. If the model is unavailable (no API
key, offline demo, etc.) we fall back to a deterministic template so the
pipeline still produces a usable alert; the fallback is not a mock of
the "real" behavior, it's the same contract with fixed phrasing instead
of generated phrasing.
"""

from __future__ import annotations
import os
import json
from .decision_engine import RiskFinding

PROMPT_TEMPLATE = """You are writing a short alert for a family member who is caring for an \
elderly parent. They are not a medical professional. Given the structured \
finding below, write:
1. A one-line "title" (max 12 words, plain language, no jargon)
2. A 2-3 sentence "body" explaining what changed and why it matters, in a calm, \
factual tone. Do not use medical abbreviations.
3. A short "suggested_action" (max 8 words), or null if no action is needed yet.

Respond as JSON with keys: title, body, suggested_action.

Rule triggered: {rule_label}
Severity: {severity}
Structured facts: {facts}
"""


def _call_gemini(finding: RiskFinding) -> dict | None:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai  # pip install google-genai
        client = genai.Client(api_key=api_key)
        prompt = PROMPT_TEMPLATE.format(
            rule_label=finding.rule_label,
            severity=finding.severity,
            facts=json.dumps(finding.facts),
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        return json.loads(resp.text)
    except Exception:
        # Network unavailable, quota issue, bad key, schema drift, etc.
        # Fall through to the deterministic template so the demo never hard-fails.
        return None


# ---------------------------------------------------------------------------
# Deterministic fallback templates, keyed by rule_id
# ---------------------------------------------------------------------------
def _template_explain(finding: RiskFinding) -> dict:
    f = finding.facts
    if finding.rule_id == "drug_supplement_interaction":
        return {
            "title": f"New medication may not mix well with her {f['conflict_name'].lower()}",
            "body": (f"Her doctor prescribed {f['drug_name']}. She has also been taking "
                      f"{f['conflict_name']} regularly. {f['clinical_note']}"),
            "suggested_action": "Call her doctor's clinic",
        }
    if finding.rule_id == "vitals_single_threshold":
        metric_label = f["metric"].replace("bp_", "blood pressure ").replace("_", " ")
        return {
            "title": f"New {metric_label} reading of {f['value']:g} is above her usual range",
            "body": (f"A fresh reading came in at {f['value']:g}, above her typical range. "
                      f"Not urgent yet — worth keeping an eye on the next few readings."),
            "suggested_action": "Add a note for the doctor",
        }
    if finding.rule_id == "vitals_trend":
        metric_label = f["metric"].replace("bp_", "blood pressure ").replace("_", " ")
        return {
            "title": f"{metric_label.capitalize()} trending up over the past week",
            "body": (f"Readings have climbed by about {f['rise']:g} points across "
                      f"{f['readings']} recent readings. Still below the urgent threshold, "
                      f"but the trend is worth watching."),
            "suggested_action": "Add a note for the doctor",
        }
    if finding.rule_id == "openfda_label_crossref":
        return {
            "title": f"{f['drug_name']}'s FDA label mentions {f['mentioned_drug']}",
            "body": (f"The official FDA label for {f['drug_name']} mentions {f['mentioned_drug']} "
                      f"in its interactions or warnings section. This is an automated text match, "
                      f"not a confirmed clinical interaction \u2014 worth a quick check with the pharmacist."),
            "suggested_action": "Ask the pharmacist to confirm",
        }
    if finding.rule_id == "meal_logging_gap":
        return {
            "title": f"Meals skipped {f['skipped_count']} times this week",
            "body": ("Caregiver notes show meals were skipped more than once in the past "
                      "week. Not yet a pattern, but worth a gentle check-in — skipped meals "
                      "can affect how medication behaves."),
            "suggested_action": None,
        }
    return {
        "title": finding.rule_label,
        "body": "A new finding was detected. Details are in the audit trail.",
        "suggested_action": None,
    }


def explain(finding: RiskFinding) -> dict:
    """Returns {title, body, suggested_action} — tries Gemini first, falls
    back to the deterministic template. Either path returns the same shape,
    so callers never need to know which one ran."""
    result = _call_gemini(finding)
    if result is None:
        result = _template_explain(finding)
    return result
