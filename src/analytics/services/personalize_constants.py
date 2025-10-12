"""
Constants for AWS Personalize data export.

This module defines event types, weights, and schema field names
used for exporting interaction data to AWS Personalize.
"""

# Event Types
BOUNTY_SOLUTION_SUBMITTED = "BOUNTY_SOLUTION_SUBMITTED"
BOUNTY_SOLUTION_AWARDED = "BOUNTY_SOLUTION_AWARDED"
RFP_CREATED = "RFP_CREATED"
PROPOSAL_CREATED = "PROPOSAL_CREATED"

# Event Weights (values for Personalize)
# These values represent the importance/weight of each event type
EVENT_WEIGHTS = {
    BOUNTY_SOLUTION_SUBMITTED: 2.0,
    BOUNTY_SOLUTION_AWARDED: 3.0,
    RFP_CREATED: 3.0,
    PROPOSAL_CREATED: 3.0,
}

# Event Type Configurations
# Each event type can be enabled/disabled and maps to a specific mapper
EVENT_TYPE_CONFIGS = {
    "bounty_solution": {
        "enabled": True,
        "mapper_class": "BountySolutionMapper",
        "description": "Bounty solution submissions and awards",
    },
    "rfp": {
        "enabled": True,
        "mapper_class": "RfpMapper",
        "description": "Request for Proposal (Grant) creation events",
    },
    "proposal": {
        "enabled": True,
        "mapper_class": "ProposalMapper",
        "description": "Proposal (Preregistration) creation events",
    },
    # Future event types can be added here:
    # "paper_view": {
    #     "enabled": False,
    #     "mapper_class": "PaperViewMapper",
    #     "description": "Paper view events"
    # },
}

# Personalize Interaction Schema Field Names
FIELD_USER_ID = "USER_ID"
FIELD_ITEM_ID = "ITEM_ID"
FIELD_EVENT_TYPE = "EVENT_TYPE"
FIELD_EVENT_VALUE = "EVENT_VALUE"
FIELD_DEVICE = "DEVICE"
FIELD_TIMESTAMP = "TIMESTAMP"
FIELD_IMPRESSION = "IMPRESSION"
FIELD_RECOMMENDATION_ID = "RECOMMENDATION_ID"

# CSV Headers for Personalize Interactions
INTERACTION_CSV_HEADERS = [
    FIELD_USER_ID,
    FIELD_ITEM_ID,
    FIELD_EVENT_TYPE,
    FIELD_EVENT_VALUE,
    FIELD_DEVICE,
    FIELD_TIMESTAMP,
    FIELD_IMPRESSION,
    FIELD_RECOMMENDATION_ID,
]
