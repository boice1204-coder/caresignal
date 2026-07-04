"""
Clinical rule definitions for CareSignal.

This is deliberately kept separate from decision_engine.py: the engine is
generic scoring/orchestration machinery, this file is where the actual
domain knowledge lives. In a real deployment this table would be reviewed
and maintained by a clinician (which is the founder's own background) —
it is the one piece of the system a general-purpose LLM cannot be trusted
to author from scratch, because getting it wrong is a patient-safety issue,
not a UX issue.

Every threshold below is illustrative for the prototype, not medical advice,
and would need clinical sign-off before any real deployment.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Rule 1 — drug / supplement interaction lookup
# ---------------------------------------------------------------------------
# Two sources feed this table:
#
#   1. A small set of hand-picked, well-established interactions (below) —
#      illustrative for the prototype, not independently validated.
#
#   2. ONCHIGH_INTERACTIONS — the 15 interactions that survived a two-round
#      expert consensus panel (21 panelists: physicians, pharmacists, EHR
#      vendors, KB vendors, FDA/ASHP representatives) commissioned by the
#      Office of the National Coordinator for Health IT. These are drug
#      pairs the panel agreed should NEVER be co-prescribed — the highest
#      confidence tier available for a rule like this.
#
#      Source: Phansalkar S, Desai AA, Bell D, et al. "High-priority
#      drug-drug interactions for use in electronic health records."
#      J Am Med Inform Assoc. 2012;19(5):735-743. doi:10.1136/amiajnl-2011-000612
#      (Table 2 — accepted interactions; drug class membership as specified
#      by the panel and by the three commercial knowledge-base vendors who
#      rated the final list.)
#
# In production this table would still need periodic review against a
# licensed, continuously-updated drug-interaction database (First Databank,
# Lexicomp, Medi-Span) — the paper itself notes its list is a "starter set,"
# not a complete one.

DRUG_INTERACTIONS = [
    {
        "drug_keywords": ["losartan", "valsartan", "irbesartan"],   # ARBs
        "conflict_keywords": ["potassium"],
        "rule_id": "drug_supplement_interaction",
        "severity": "urgent",
        "clinical_note": (
            "ARB blood-pressure medications reduce potassium excretion. "
            "Combined with a potassium supplement, this can raise blood "
            "potassium (hyperkalemia) to dangerous levels."
        ),
    },
    {
        "drug_keywords": ["lisinopril", "enalapril", "ramipril"],   # ACE inhibitors
        "conflict_keywords": ["potassium"],
        "rule_id": "drug_supplement_interaction",
        "severity": "urgent",
        "clinical_note": (
            "ACE inhibitors reduce potassium excretion. Combined with a "
            "potassium supplement, this can raise blood potassium "
            "(hyperkalemia) to dangerous levels."
        ),
    },
    {
        "drug_keywords": ["warfarin"],
        "conflict_keywords": ["vitamin k", "fish oil", "ginkgo"],
        "rule_id": "drug_supplement_interaction",
        "severity": "urgent",
        "clinical_note": (
            "This combination can change how well warfarin controls "
            "blood clotting, raising bleeding or clotting risk."
        ),
    },
]


# ---- reusable class keyword lists, taken from Table 2's stated membership ----
_MAO_INHIBITORS = ["tranylcypromine", "phenelzine", "isocarboxazid", "procarbazine", "selegiline"]

_ONCHIGH_CLASSES = {
    "amphetamine_derivatives": [
        "dexmethylphenidate", "dextroamphetamine", "methylphenidate", "lisdexamfetamine",
        "methamphetamine", "phendimetrazine", "pseudoephedrine", "amphetamine",
        "benzphetamine", "diethylpropion", "phentermine", "atomoxetine",
    ],
    "ppis": ["omeprazole", "lansoprazole", "pantoprazole", "rabeprazole", "esomeprazole"],
    "ssris_and_related": [
        "fluoxetine", "paroxetine", "citalopram", "escitalopram", "sertraline",
        "fluvoxamine", "duloxetine", "nefazodone", "desvenlafaxine", "milnacipran", "venlafaxine",
    ],
    "cyp3a4_inhibitors": [
        "ritonavir", "nelfinavir", "atazanavir", "indinavir", "saquinavir", "amprenavir",
        "darunavir", "lopinavir", "tipranavir", "fosamprenavir", "clarithromycin", "erythromycin",
        "telithromycin", "amiodarone", "verapamil", "diltiazem", "ketoconazole", "itraconazole",
        "fluconazole", "voriconazole", "nefazodone", "aprepitant", "cimetidine",
    ],
    "narcotic_analgesics": ["meperidine", "methadone", "tapentadol", "fentanyl", "tramadol", "dextromethorphan"],
    "cyp1a2_inhibitors_ramelteon": ["fluvoxamine", "amiodarone", "ticlopidine", "ciprofloxacin"],
    "strong_cyp3a4_inducers": ["bosentan", "rifapentine", "carbamazepine", "rifabutin", "rifampin", "st john's wort"],
    "protease_inhibitors": [
        "ritonavir", "amprenavir", "atazanavir", "darunavir", "fosamprenavir",
        "indinavir", "lopinavir", "nelfinavir", "saquinavir", "tipranavir",
    ],
    "statins_high_risk": ["simvastatin", "lovastatin"],
    "cyp3a4_inhibitors_for_ergot": [
        "indinavir", "saquinavir", "tipranavir", "ritonavir", "nelfinavir", "atazanavir",
        "amprenavir", "darunavir", "lopinavir", "clarithromycin", "erythromycin",
        "telithromycin", "ketoconazole", "itraconazole", "voriconazole",
    ],
    "ergot_alkaloids": ["ergotamine", "methylergonovine", "dihydroergotamine", "ergonovine"],
    "cyp1a2_inhibitors_tizanidine": [
        "ciprofloxacin", "fluvoxamine", "mexiletine", "propafenone", "zileuton", "amiodarone", "ticlopidine",
    ],
    "triptans": ["sumatriptan", "zolmitriptan", "rizatriptan"],
    "mao_inhibitors_for_triptans": ["tranylcypromine", "phenelzine", "isocarboxazid", "moclobemide", "methylene blue"],
    # NOTE: standard TCA membership added for implementation completeness —
    # Table 2 names the class ("Tricyclic antidepressants") but does not
    # enumerate members, unlike the other rows. This list is NOT from the paper.
    "tcas_supplementary": [
        "amitriptyline", "nortriptyline", "imipramine", "desipramine",
        "clomipramine", "doxepin", "trimipramine", "protriptyline",
    ],
}

_CITATION = "ONCHigh consensus list \u2014 Phansalkar et al. 2012, JAMIA (doi:10.1136/amiajnl-2011-000612)"

ONCHIGH_INTERACTIONS = [
    {
        "drug_keywords": _ONCHIGH_CLASSES["amphetamine_derivatives"], "conflict_keywords": _MAO_INHIBITORS,
        "rule_id": "onchigh_ddi_3", "severity": "urgent",
        "clinical_note": f"Combining a stimulant/amphetamine-class drug with an MAO inhibitor risks a life-threatening hypertensive crisis. {_CITATION}",
    },
    {
        "drug_keywords": ["atazanavir"], "conflict_keywords": _ONCHIGH_CLASSES["ppis"],
        "rule_id": "onchigh_ddi_4", "severity": "urgent",
        "clinical_note": f"Proton pump inhibitors raise stomach pH and can sharply reduce atazanavir absorption, risking loss of HIV viral control. {_CITATION}",
    },
    {
        "drug_keywords": ["febuxostat"], "conflict_keywords": ["azathioprine", "mercaptopurine"],
        "rule_id": "onchigh_ddi_6", "severity": "urgent",
        "clinical_note": f"Febuxostat can block the breakdown of azathioprine/mercaptopurine, raising levels to the point of severe bone-marrow suppression. {_CITATION}",
    },
    {
        "drug_keywords": _ONCHIGH_CLASSES["ssris_and_related"], "conflict_keywords": _MAO_INHIBITORS,
        "rule_id": "onchigh_ddi_8", "severity": "urgent",
        "clinical_note": f"Combining an SSRI-class antidepressant with an MAO inhibitor risks serotonin syndrome, a potentially life-threatening reaction. {_CITATION}",
    },
    {
        "drug_keywords": ["irinotecan"], "conflict_keywords": _ONCHIGH_CLASSES["cyp3a4_inhibitors"],
        "rule_id": "onchigh_ddi_11", "severity": "urgent",
        "clinical_note": f"Strong CYP3A4 inhibitors can raise irinotecan to toxic levels, increasing risk of severe, potentially life-threatening side effects. {_CITATION}",
    },
    {
        "drug_keywords": _ONCHIGH_CLASSES["narcotic_analgesics"], "conflict_keywords": _MAO_INHIBITORS,
        "rule_id": "onchigh_ddi_16", "severity": "urgent",
        "clinical_note": f"This combination risks serotonin syndrome or dangerous central-nervous-system depression. {_CITATION}",
    },
    {
        "drug_keywords": _ONCHIGH_CLASSES["tcas_supplementary"], "conflict_keywords": _MAO_INHIBITORS,
        "rule_id": "onchigh_ddi_20", "severity": "urgent",
        "clinical_note": f"This combination risks serotonin syndrome or a hypertensive crisis. {_CITATION} (TCA member list supplemented \u2014 not enumerated in the source table.)",
    },
    {
        "drug_keywords": ["ramelteon"], "conflict_keywords": _ONCHIGH_CLASSES["cyp1a2_inhibitors_ramelteon"],
        "rule_id": "onchigh_ddi_22", "severity": "urgent",
        "clinical_note": f"These CYP1A2 inhibitors can sharply raise ramelteon levels, increasing sedation and fall risk. {_CITATION}",
    },
    {
        "drug_keywords": _ONCHIGH_CLASSES["strong_cyp3a4_inducers"], "conflict_keywords": _ONCHIGH_CLASSES["protease_inhibitors"],
        "rule_id": "onchigh_ddi_23", "severity": "urgent",
        "clinical_note": f"Strong CYP3A4 inducers can speed up the breakdown of HIV protease inhibitors, risking loss of viral control. {_CITATION}",
    },
    {
        "drug_keywords": _ONCHIGH_CLASSES["statins_high_risk"], "conflict_keywords": _ONCHIGH_CLASSES["cyp3a4_inhibitors"],
        "rule_id": "onchigh_ddi_25", "severity": "urgent",
        "clinical_note": f"CYP3A4 inhibitors can raise simvastatin/lovastatin levels enough to cause severe muscle breakdown (rhabdomyolysis). {_CITATION}",
    },
    {
        "drug_keywords": _ONCHIGH_CLASSES["cyp3a4_inhibitors_for_ergot"], "conflict_keywords": _ONCHIGH_CLASSES["ergot_alkaloids"],
        "rule_id": "onchigh_ddi_27", "severity": "urgent",
        "clinical_note": f"CYP3A4 inhibitors can raise ergot-drug levels enough to cause dangerous vasospasm and tissue damage (ergotism). {_CITATION}",
    },
    {
        "drug_keywords": ["tizanidine"], "conflict_keywords": _ONCHIGH_CLASSES["cyp1a2_inhibitors_tizanidine"],
        "rule_id": "onchigh_ddi_28", "severity": "urgent",
        "clinical_note": f"These CYP1A2 inhibitors can raise tizanidine levels enough to cause dangerously low blood pressure and sedation. {_CITATION}",
    },
    {
        "drug_keywords": ["tranylcypromine"], "conflict_keywords": ["procarbazine"],
        "rule_id": "onchigh_ddi_30", "severity": "urgent",
        "clinical_note": f"Both drugs have MAO-inhibiting activity; combining them risks a severe hypertensive crisis. {_CITATION}",
    },
    {
        "drug_keywords": _ONCHIGH_CLASSES["triptans"], "conflict_keywords": _ONCHIGH_CLASSES["mao_inhibitors_for_triptans"],
        "rule_id": "onchigh_ddi_31", "severity": "urgent",
        "clinical_note": f"This combination can raise triptan levels and risks serotonin syndrome. {_CITATION}",
    },
]

# NOTE — deliberately NOT implemented: DDI #21, "QT prolonging agents +
# QT prolonging agents" (Table 2). The panel's member list for this class
# is external (http://www.torsades.org / CredibleMeds), and was not
# reproduced in the paper's own table. Rather than guess at membership for
# a rule about cardiac arrhythmia risk, this is left as a documented gap —
# pull the current list from CredibleMeds (credibledmeds.org) before adding it.

DRUG_INTERACTIONS = DRUG_INTERACTIONS + ONCHIGH_INTERACTIONS


# ---------------------------------------------------------------------------
# Rule 2 — vitals thresholds + trend
# ---------------------------------------------------------------------------
@dataclass
class VitalsThreshold:
    metric: str
    urgent_at: float
    watch_at: float
    direction: str  # 'above' | 'below'


VITALS_THRESHOLDS = [
    VitalsThreshold(metric="bp_systolic", urgent_at=160, watch_at=150, direction="above"),
    VitalsThreshold(metric="bp_diastolic", urgent_at=100, watch_at=95, direction="above"),
    VitalsThreshold(metric="glucose", urgent_at=250, watch_at=200, direction="above"),
]

TREND_WINDOW_DAYS = 7
TREND_MIN_READINGS = 3
TREND_RISE_WATCH = 15.0   # points risen across the window to flag "watch"


# ---------------------------------------------------------------------------
# Rule 3 — meal-logging gap
# ---------------------------------------------------------------------------
MEAL_GAP_WINDOW_DAYS = 7
MEAL_GAP_MIN_SKIPS = 2
