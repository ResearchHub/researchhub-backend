"""
Constants for figure selection criteria weights.

These weights are used when constructing prompts for AWS Bedrock to select
the primary image from extracted figures.
"""

ASPECT_RATIO_MATCH_WEIGHT = 8
SCIENTIFIC_IMPACT_WEIGHT = 18
VISUAL_QUALITY_WEIGHT = 18
DATA_DENSITY_WEIGHT = 8
NARRATIVE_CONTEXT_WEIGHT = 18
INTERPRETABILITY_WEIGHT = 12
UNIQUENESS_WEIGHT = 5
SOCIAL_MEDIA_POTENTIAL_WEIGHT = 20

# Total weight should equal 100
TOTAL_WEIGHT = (
    ASPECT_RATIO_MATCH_WEIGHT
    + SCIENTIFIC_IMPACT_WEIGHT
    + VISUAL_QUALITY_WEIGHT
    + DATA_DENSITY_WEIGHT
    + NARRATIVE_CONTEXT_WEIGHT
    + INTERPRETABILITY_WEIGHT
    + UNIQUENESS_WEIGHT
    + SOCIAL_MEDIA_POTENTIAL_WEIGHT
)

# If the best figure scores below this, we'll use a preview instead
MIN_PRIMARY_SCORE_THRESHOLD = 50

CRITERIA_DESCRIPTIONS = {
    "aspect_ratio_match": {
        "weight": ASPECT_RATIO_MATCH_WEIGHT,
        "description": "Compatibility with standard feed dimensions (16:9, 4:3, 1:1)",
        "key_metrics": "Distance from ideal ratio",
    },
    "scientific_impact": {
        "weight": SCIENTIFIC_IMPACT_WEIGHT,
        "description": "Presents primary findings, conclusions, or key methods of the paper",
        "key_metrics": "Central vs supporting result, methods figures (e.g., imaging, staining)",
    },
    "visual_quality": {
        "weight": VISUAL_QUALITY_WEIGHT,
        "description": "Clarity, resolution, color fidelity, professional appearance, readability",
        "key_metrics": "DPI, color depth, artifacts, text size and legibility, contrast",
    },
    "data_density": {
        "weight": DATA_DENSITY_WEIGHT,
        "description": "Information richness vs white space ratio",
        "key_metrics": "Dimensions, number of curves/plots",
    },
    "narrative_context": {
        "weight": NARRATIVE_CONTEXT_WEIGHT,
        "description": "Ability to serve as paper introduction, overview, or summary figure",
        "key_metrics": "Structural overview vs detail, provides context for the paper",
    },
    "interpretability": {
        "weight": INTERPRETABILITY_WEIGHT,
        "description": "Self-explanatory legends, labels, intuitive presentation, readability",
        "key_metrics": "Axis labels, color coding clarity, text size and legibility",
    },
    "uniqueness": {
        "weight": UNIQUENESS_WEIGHT,
        "description": "Data or analysis specific to this paper",
        "key_metrics": "Appears in other papers",
    },
    "social_media_potential": {
        "weight": SOCIAL_MEDIA_POTENTIAL_WEIGHT,
        "description": "Visual appeal, eye-catching quality for Twitter/Instagram/LinkedIn sharing",
        "key_metrics": "Visual interest, discovery-worthy, stands out, color appeal",
    },
}
