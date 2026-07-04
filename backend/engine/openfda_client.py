"""
openFDA integration — augments the curated interaction table in rules.py
with live lookups against the FDA's public drug label API.

Why this exists: rules.py has a handful of hand-picked, well-established
interactions (ARB/ACE + potassium, warfarin + vitamin K/fish oil/ginkgo).
That list is deliberately small and deliberately conservative — it's the
part a clinician should review line by line. openFDA lets us extend
*coverage* (many more drugs) without extending the *hand-maintained*
surface area, by checking each drug's official FDA label for interaction
language that mentions another drug the subject is taking.

This is NOT a replacement for the curated table. It's a lower-confidence,
best-effort second pass: free-text matching against label prose is noisier
than a reviewed lookup table, so findings from this module are always
capped at "watch" severity (never "urgent"), and are clearly tagged with
their source label so a caregiver (or judge) can check the primary source.

API docs: https://open.fda.gov/apis/drug/label/
No API key required for light/demo use. Rate limits apply for sustained
production use — see openFDA's documentation for current limits.

Network note: this module was written and unit-tested with a *mocked*
HTTP layer (see tests/test_openfda_client.py) because the sandbox this
was built in does not have network egress to api.fda.gov. The query
shape and field names are taken directly from openFDA's published API
docs. Run scripts/smoke_test_openfda.py once on a machine with normal
internet access before the demo to confirm live behavviour end to end.
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Optional

import requests

OPENFDA_LABEL_ENDPOINT = "https://api.fda.gov/drug/label.json"
REQUEST_TIMEOUT_SECONDS = 4
CACHE_TTL_SECONDS = 24 * 60 * 60  # label text changes rarely; cache for a day


@dataclass
class DrugLabel:
    generic_name: str
    drug_interactions_text: str
    warnings_text: str
    contraindications_text: str
    spl_set_id: Optional[str]
    source_url: str


class OpenFDAClient:
    """Thin, cached, defensive client for the openFDA drug label endpoint.

    Defensive by design: any network error, timeout, unexpected schema, or
    empty result returns None rather than raising, so a flaky connection
    during a demo degrades to "no extra findings" instead of crashing the
    pipeline. The curated rules in rules.py always run regardless of
    whether this client can reach the network.
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._cache: dict[str, tuple[float, Optional[DrugLabel]]] = {}

    def get_label(self, generic_name: str) -> Optional[DrugLabel]:
        key = generic_name.strip().lower()
        cached = self._cache.get(key)
        if cached and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        label = self._fetch(key)
        self._cache[key] = (time.time(), label)
        return label

    def _fetch(self, generic_name: str) -> Optional[DrugLabel]:
        params = {
            "search": f'openfda.generic_name:"{generic_name}"',
            "limit": 1,
        }
        try:
            resp = self._session.get(
                OPENFDA_LABEL_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT_SECONDS
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get("results") or []
            if not results:
                return None
            r = results[0]
            return DrugLabel(
                generic_name=generic_name,
                drug_interactions_text=" ".join(r.get("drug_interactions", []) or []),
                warnings_text=" ".join(r.get("warnings", []) or []),
                contraindications_text=" ".join(r.get("contraindications", []) or []),
                spl_set_id=(r.get("openfda", {}) or {}).get("spl_set_id", [None])[0],
                source_url=resp.url,
            )
        except (requests.RequestException, ValueError, KeyError, IndexError):
            # Network down, timeout, malformed JSON, unexpected shape, etc.
            # This is a best-effort augmentation layer — fail quiet, not loud.
            return None


def label_mentions_drug(label: DrugLabel, other_drug_keyword: str) -> bool:
    """Very deliberately simple: case-insensitive substring match against
    the interactions + warnings text. This will produce false negatives
    (label prose is inconsistent) and occasional false positives (the drug
    name appears in an unrelated sentence) — which is exactly why findings
    built on this are capped at 'watch', not 'urgent'. It's a recall aid
    for a human, not a clinical verdict."""
    haystack = f"{label.drug_interactions_text} {label.warnings_text}".lower()
    return other_drug_keyword.strip().lower() in haystack
