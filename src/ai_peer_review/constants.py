# Bedrock Converse `maxTokens` for structured proposal review JSON.
PROPOSAL_REVIEW_MAX_OUTPUT_TOKENS = 16384

AI_PEER_REVIEW_EXPERT_EMAIL_DEFAULT = "ai-review@researchhub.foundation"

AUTO_PR_DAILY_CAP_PER_GRANT_DEFAULT = 10
AUTO_KI_DAILY_CAP_PER_REVIEW_DEFAULT = 20


CATEGORY_KEYS = [
    "overall_impact",
    "importance_significance_innovation",
    "rigor_and_feasibility",
    "additional_review_criteria",
]

CATEGORY_ITEMS = {
    "overall_impact": [
        "novelty",
        "rigor",
        "reproducibility",
        "field_impact",
    ],
    "importance_significance_innovation": [
        "hypothesis_strength",
        "work_novelty",
        "question_importance",
        "advances_knowledge",
    ],
    "rigor_and_feasibility": [
        "study_design",
        "methodology",
        "timeline_feasibility",
        "team_qualifications",
        "research_environment",
        "budget_appropriateness_justification",
    ],
    "additional_review_criteria": [
        "human_or_animal_protections",
        "resubmission_critiques_addressed",
        "open_science_adherence",
        "ai_use_disclosed",
        "conflicts_of_interest_disclosed",
    ],
}


CRITICAL_FAIL_ITEMS = frozenset(
    {
        ("rigor_and_feasibility", "study_design"),
        ("rigor_and_feasibility", "methodology"),
        ("rigor_and_feasibility", "timeline_feasibility"),
    }
)
