"""
Constants for figure selection criteria weights.

These weights are used when constructing prompts for AWS Bedrock to select
the primary image from extracted figures.
"""

ASPECT_RATIO_MATCH_WEIGHT = 10
SCIENTIFIC_IMPACT_WEIGHT = 22
VISUAL_QUALITY_WEIGHT = 13
DATA_DENSITY_WEIGHT = 10
NARRATIVE_CONTEXT_WEIGHT = 15
INTERPRETABILITY_WEIGHT = 10
UNIQUENESS_WEIGHT = 5
SOCIAL_MEDIA_POTENTIAL_WEIGHT = 15

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
        "description": "Presents primary findings & conclusions of the paper",
        "key_metrics": "Central vs supporting result",
    },
    "visual_quality": {
        "weight": VISUAL_QUALITY_WEIGHT,
        "description": "Clarity, resolution, color fidelity, professional appearance",
        "key_metrics": "DPI, color depth, artifacts",
    },
    "data_density": {
        "weight": DATA_DENSITY_WEIGHT,
        "description": "Information richness vs white space ratio",
        "key_metrics": "Dimensions, number of curves/plots",
    },
    "narrative_context": {
        "weight": NARRATIVE_CONTEXT_WEIGHT,
        "description": "Ability to serve as paper introduction or overview",
        "key_metrics": "Structural overview vs detail",
    },
    "interpretability": {
        "weight": INTERPRETABILITY_WEIGHT,
        "description": "Self-explanatory legends, labels, intuitive presentation",
        "key_metrics": "Axis labels, color coding clarity",
    },
    "uniqueness": {
        "weight": UNIQUENESS_WEIGHT,
        "description": "Data or analysis specific to this paper",
        "key_metrics": "Appears in other papers",
    },
    "social_media_potential": {
        "weight": SOCIAL_MEDIA_POTENTIAL_WEIGHT,
        "description": "Visual appeal for Twitter/Instagram/LinkedIn sharing",
        "key_metrics": "Visual interest, discovery-worthy",
    },
}
