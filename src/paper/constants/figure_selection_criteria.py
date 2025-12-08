"""
Constants for figure selection criteria weights.

These weights are used when constructing prompts for AWS Bedrock to select
the primary image from extracted figures. Weights can be easily modified here
to adjust the selection algorithm.
"""

# Aspect Ratio Match (10%)
# Compatibility with standard feed dimensions (16:9, 4:3, 1:1)
# Key Metrics: Distance from ideal ratio
ASPECT_RATIO_MATCH_WEIGHT = 10

# Scientific Impact (22%)
# Presents primary findings & conclusions of the paper
# Key Metrics: Central vs supporting result
SCIENTIFIC_IMPACT_WEIGHT = 22

# Visual Quality (13%)
# Clarity, resolution, color fidelity, professional appearance
# Key Metrics: DPI, color depth, artifacts
VISUAL_QUALITY_WEIGHT = 13

# Data Density (10%)
# Information richness vs white space ratio
# Key Metrics: Dimensions, number of curves/plots
DATA_DENSITY_WEIGHT = 10

# Narrative Context (15%)
# Ability to serve as paper introduction or overview
# Key Metrics: Structural overview vs detail
NARRATIVE_CONTEXT_WEIGHT = 15

# Interpretability (10%)
# Self-explanatory legends, labels, intuitive presentation
# Key Metrics: Axis labels, color coding clarity
INTERPRETABILITY_WEIGHT = 10

# Uniqueness (5%)
# Data or analysis specific to this paper
# Key Metrics: Appears in other papers
UNIQUENESS_WEIGHT = 5

# Social Media Potential (15%)
# Visual appeal for Twitter/Instagram/LinkedIn sharing
# Key Metrics: Visual interest, discovery-worthy
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

# Minimum score threshold for primary image selection
# If the best figure scores below this, we'll use a preview instead
MIN_PRIMARY_SCORE_THRESHOLD = 70  # Percentage (0-100)

# Criteria descriptions for prompt construction
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
