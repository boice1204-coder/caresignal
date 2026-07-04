# CareSignal — backend skeleton

This is the decision-engine backend behind the CareSignal prototype: the
part that actually does the "acceleration" work the pitch talks about,
not just a UI that claims it.

## Why this exists

The hackathon brief asks for a data intelligence tool people would
*actually use*, and proof that it makes decisions faster or better. A
chatbot wrapper can't prove that — it can only assert it. This backend
proves it two ways:

1. **The decision logic is deterministic and testable.** `engine/rules.py`
   encodes the actual clinical checks (drug-supplement interactions,
   vitals thresholds/trends, meal-logging gaps). `engine/decision_engine.py`
   runs them against real data and returns a finding *with its exact
   evidence trail* — no LLM is involved in deciding whether something is
   risky. `tests/test_decision_engine.py` has 11 passing unit tests
   proving each rule fires (and stays silent) correctly.
2. **The speed claim is measured, not asserted.** `run_all_rules()`
   times itself. Running the full rule set against the demo fixture
   scores in single-digit milliseconds — the "under 5 seconds" / "15-30
   minutes manually" comparison on slide 6 comes from this number.

Gemini only enters at the very last step (`engine/gemini_explainer.py`),
to phrase an already-decided finding in plain language. It never decides
whether a risk exists — that split is what makes every alert auditable
back to a specific rule and a specific piece of source data, which is
exactly what the wireframe's "Why am I seeing this?" panel shows.

## Project layout

```
backend/
  sql/schema.sql            BigQuery DDL for the production dataset
  docs/Phansalkar_2012_ONCHigh_JAMIA.pdf   archived source paper for the ONCHigh rules
  engine/
    rules.py                the clinical knowledge (interaction table, thresholds)
    decision_engine.py       runs the rules, returns RiskFinding + evidence trail
    data_access.py           DataSource interface: LocalDataSource (demo) / BigQueryDataSource (prod)
    openfda_client.py        live augmentation: cross-checks FDA drug labels (see below)
    gemini_explainer.py      turns a RiskFinding into plain-language alert copy
  pipeline/run_pipeline.py   end-to-end demo: ingest -> score -> explain -> alert JSON
  scripts/smoke_test_openfda.py   manual, non-mocked check against the real api.fda.gov
  data/
    generate_sample_events.py   builds the "Tan Ah Hoon" demo fixture (same subject as the wireframe)
    sample_events.json          generated fixture
    pipeline_output.json        generated after running the pipeline
  tests/
    test_decision_engine.py     11 tests for the 3 hand-picked rules + engine mechanics
    test_onchigh_interactions.py  6 tests for the literature-sourced interaction list
    test_openfda_client.py      9 tests for the openFDA module, HTTP mocked, no network needed
```

## Run it

```bash
pip install -r requirements.txt
cd tests && python3 -m pytest -v                # 27 tests, no GCP project or network needed
cd ../pipeline && python3 run_pipeline.py         # runs the "Tan Ah Hoon" scenario, curated rules only
```

`run_pipeline.py` prints each alert plus the measured scoring latency, and
writes `data/pipeline_output.json` in the same shape the wireframe's alert
cards expect (`title`, `body`, `suggested_action`, `severity`, `trace[]`) —
so the two deliverables are demonstrably telling the same story with the
same data.

## Is the clinical rule table validated against anything?

As of this update: **partially, and now much more so than before.**

`rules.py` has two tiers:

1. A small set of hand-picked, well-established interactions (ARB/ACE +
   potassium, warfarin + vitamin K/fish oil/ginkgo) — illustrative,
   not independently validated.
2. **`ONCHIGH_INTERACTIONS`** — 14 of the 15 interactions from a real,
   peer-reviewed expert-consensus panel: Phansalkar S, Desai AA, Bell D,
   et al. "High-priority drug-drug interactions for use in electronic
   health records." *J Am Med Inform Assoc.* 2012;19(5):735-743.
   doi:10.1136/amiajnl-2011-000612. 21 panelists (physicians, pharmacists,
   EHR/knowledge-base vendors, FDA and ASHP representatives), commissioned
   by the ONC, narrowed 31 candidate interactions down to 15 that should
   *never* be co-prescribed. The full paper is archived at
   `docs/Phansalkar_2012_ONCHigh_JAMIA.pdf` for reference/citation.

   One of the 15 (QT-prolonging agents x QT-prolonging agents) is
   **deliberately not implemented** — the paper references an external
   member list (torsades.org / CredibleMeds) rather than enumerating it
   in the table, and `tests/test_onchigh_interactions.py` has a tripwire
   test that fails on purpose if someone adds a rule_id for it without
   also sourcing that list properly. The TCA (tricyclic antidepressant)
   member list for DDI #20 was supplemented with standard pharmacology
   references since the paper names the class but not its members —
   this is flagged in a code comment, not presented as verbatim from
   the source.

To extend coverage further without hand-maintaining an ever-growing
table, `engine/openfda_client.py` adds a second, lower-confidence check
(see below) — free-text matching against FDA label prose, capped at
"watch" severity, never "urgent".

Two things worth knowing:

1. **NLM's old dedicated Drug-Drug Interaction API (RxNav) was discontinued
   in January 2024 and has not returned.** If you see older tutorials
   referencing it, that path no longer works — `openfda_client.py` was
   built as a replacement path (label text matching), not by mistake.
2. There is also a small, peer-reviewed, expert-consensus list of 15
   high-priority drug-drug interactions (Phansalkar et al., 2012, *JAMIA*)
   that would be an excellent citable addition to `rules.py`'s curated
   table. It's behind a journal paywall that this build environment
   couldn't get through automatically — worth pulling via NTU's library
   access and adding by hand, since it's small enough to review line by
   line (which is exactly the kind of source a hand-maintained safety
   table should be built from).

### A note on testing without network access

This project was built in a sandbox with no egress to `api.fda.gov`, so
`engine/openfda_client.py` was written directly against openFDA's
published API documentation (field names, query syntax, response shape)
rather than against live responses. `tests/test_openfda_client.py` covers
the parsing, caching, and error-handling logic with mocked HTTP responses
matching that documented shape — including a real bug the tests caught
during development (an inconsistent name-normalization that caused the
same interaction to be reported twice, once per direction).

**`scripts/smoke_test_openfda.py` has not been run against the live API**
and should be run once, on a machine with normal internet access, before
relying on this in a live demo. If the demo network can't reach
`api.fda.gov` either, that's fine — `run_all_rules(..., include_openfda=False)`
is the default, and the curated table keeps working with zero dependency
on outside network access.

## How this maps to the real Google Cloud architecture (slide 8)

| Architecture box | This repo |
|---|---|
| Pub/Sub + Cloud Functions (ingestion) | not built yet — `data_access.py` assumes data has already landed in the source tables; ingestion functions are the next piece to build |
| BigQuery (data layer) | `sql/schema.sql` — real DDL, ready to deploy with `bq query` or Terraform |
| Decision engine (core IP) | `engine/rules.py` + `engine/decision_engine.py` — runs as-is today, swap `LocalDataSource` -> `BigQueryDataSource` to point at production |
| — coverage augmentation | `engine/openfda_client.py` — live cross-check against FDA drug labels, opt-in via `include_openfda=True`, capped at "watch" severity |
| Vertex AI Pipelines (orchestration) | `pipeline/run_pipeline.py` is the local equivalent of a pipeline run; wrapping this in a `@component`/`@pipeline` definition is a day of work once a GCP project exists |
| Gemini (explanation layer) | `engine/gemini_explainer.py` — calls `gemini-2.5-flash` if `GOOGLE_API_KEY` is set, otherwise uses a deterministic template so the demo never depends on a live key |
| Audit trail | every `RiskFinding.trace` entry maps 1:1 to a row in `caresignal.audit_trail` |

## What's deliberately not here yet

- Real ingestion (Pub/Sub topics, Cloud Functions, OCR for prescription
  photos). `LocalDataSource` stands in for "data has already landed."
- Deploying `sql/schema.sql` to an actual BigQuery dataset and wiring
  `BigQueryDataSource` up to it — needs a GCP project.
- The BigQuery ML trend-anomaly model sketched at the bottom of
  `schema.sql` (commented out) — the current trend rule is a plain
  rolling-window slope check, which is enough to demo and easy to
  explain to a judge; the ML model is a credible "next step," not a
  prerequisite.
- Live confirmation that `openfda_client.py` behaves as expected against
  the real api.fda.gov (see the note above) — the logic is tested against
  a mocked, documentation-accurate response shape, but hasn't had a live
  network run yet.
- DDI #21 from the ONCHigh list (QT-prolonging agents x QT-prolonging
  agents) — needs the CredibleMeds/torsades.org member list, which isn't
  reproduced in the source paper's own table. See the tripwire test in
  `test_onchigh_interactions.py`.
