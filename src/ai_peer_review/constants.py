# Bedrock Converse `maxTokens` for structured proposal review JSON.
PROPOSAL_REVIEW_MAX_OUTPUT_TOKENS = 16384


CATEGORY_KEYS = [
    "funding_opportunity_fit",
    "methods_rigor",
    "statistical_analysis_plan",
    "feasibility_and_execution",
    "scientific_impact",
    "clinical_or_translational_impact",
    "societal_and_broader_impact",
]

CATEGORY_ITEMS = {
    "funding_opportunity_fit": [
        "fit_modality",
        "fit_aims",
        "fit_deliverables",
        "fit_scope",
    ],
    "methods_rigor": [
        "methods_detail",
        "parameters_specified",
        "controls_defined",
        "model_choice_justified",
        "outcomes_linked_to_aims",
    ],
    "statistical_analysis_plan": [
        "analysis_present",
        "power_analysis",
        "multiple_comparisons",
        "metrics_defined",
        "analysis_matches_design",
    ],
    "feasibility_and_execution": [
        "recruitment_feasible",
        "procedures_feasible",
        "timeline_milestones",
        "team_environment",
        "ethics_data_quality",
    ],
    "scientific_impact": [
        "advances_understanding",
        "generalizability",
        "opens_new_directions",
    ],
    "clinical_or_translational_impact": [
        "clinical_pathway",
        "unmet_need",
        "milestones_defined",
    ],
    "societal_and_broader_impact": [
        "societal_challenge",
        "public_communication",
        "commercial_potential",
    ],
}

OPTIONAL_CATEGORIES = frozenset(
    {
        "statistical_analysis_plan",
        "clinical_or_translational_impact",
        "societal_and_broader_impact",
    }
)

CRITICAL_FAIL_ITEMS = frozenset(
    {
        ("methods_rigor", "methods_detail"),
        ("methods_rigor", "controls_defined"),
        ("statistical_analysis_plan", "analysis_present"),
        ("statistical_analysis_plan", "power_analysis"),
        ("feasibility_and_execution", "timeline_milestones"),
    }
)
