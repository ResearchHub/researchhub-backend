# Bedrock Converse `maxTokens` for structured proposal review JSON.
PROPOSAL_REVIEW_MAX_OUTPUT_TOKENS = 16384


DIMENSION_KEYS = [
    "fundability",
    "feasibility",
    "novelty",
    "impact",
    "reproducibility",
]

DIMENSION_SUB_AREAS = {
    "fundability": ["scope_alignment", "budget_adequacy", "timeline_realism"],
    "feasibility": [
        "investigator_expertise",
        "institutional_capacity",
        "track_record",
    ],
    "novelty": [
        "conceptual_novelty",
        "methodological_novelty",
        "literature_positioning",
    ],
    "impact": [
        "scientific_impact",
        "clinical_translational_impact",
        "societal_broader_impact",
        "community_ecosystem_impact",
    ],
    "reproducibility": [
        "methods_rigor",
        "statistical_analysis_plan",
        "data_code_transparency",
        "gold_standard_methodology",
        "validation_robustness",
    ],
}

OPTIONAL_SUB_AREAS = frozenset(
    {
        ("feasibility", "track_record"),
        ("impact", "clinical_translational_impact"),
        ("impact", "community_ecosystem_impact"),
        ("reproducibility", "gold_standard_methodology"),
    }
)
