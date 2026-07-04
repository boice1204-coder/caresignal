"""
Smoke test for the openFDA integration against the REAL, LIVE api.fda.gov —
deliberately kept separate from tests/ (which is all mocked and safe to run
anywhere, including CI, with no network).

This script needs actual internet access to api.fda.gov. It was written
and code-reviewed in a sandbox that could not reach that domain, so it
has not been run end-to-end yet — run it once on a normal internet
connection before the hackathon demo to confirm live behaviour matches
what the mocked tests assume.

Run: python3 scripts/smoke_test_openfda.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.openfda_client import OpenFDAClient, label_mentions_drug

TEST_DRUGS = ["losartan", "lisinopril", "warfarin", "metformin"]


def main():
    client = OpenFDAClient()
    print("Querying live api.fda.gov for", len(TEST_DRUGS), "drugs...\n")

    any_success = False
    for name in TEST_DRUGS:
        label = client.get_label(name)
        if label is None:
            print(f"  [MISS] {name}: no label returned (check spelling, or the API may be rate-limiting)")
            continue
        any_success = True
        snippet = label.drug_interactions_text[:140].replace("\n", " ")
        print(f"  [OK]   {name}")
        print(f"         spl_set_id: {label.spl_set_id}")
        print(f"         drug_interactions (first 140 chars): {snippet}...")
        print()

    if not any_success:
        print("No labels came back at all. Check: (1) internet access, (2) that api.fda.gov")
        print("is reachable from this network, (3) openFDA isn't rate-limiting this IP.")
        sys.exit(1)

    # sanity-check the cross-reference logic against a real label
    losartan = client.get_label("losartan")
    if losartan:
        mentions_potassium = label_mentions_drug(losartan, "potassium")
        print(f"Does losartan's real FDA label mention 'potassium'? -> {mentions_potassium}")
        if not mentions_potassium:
            print("NOTE: if this is False, the free-text match in check_openfda_crossref")
            print("      may need a broader keyword (e.g. also try 'hyperkalemia').")

    print("\nSmoke test complete.")


if __name__ == "__main__":
    main()
