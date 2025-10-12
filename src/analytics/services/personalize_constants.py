"""
Constants for AWS Personalize data export.

This module defines event types, weights, and schema field names
used for exporting interaction data to AWS Personalize.
"""

# Event Types
BOUNTY_SOLUTION_SUBMITTED = "BOUNTY_SOLUTION_SUBMITTED"
BOUNTY_SOLUTION_AWARDED = "BOUNTY_SOLUTION_AWARDED"
BOUNTY_CREATED = "BOUNTY_CREATED"
BOUNTY_CONTRIBUTED = "BOUNTY_CONTRIBUTED"
RFP_CREATED = "RFP_CREATED"
RFP_APPLIED = "RFP_APPLIED"
PROPOSAL_CREATED = "PROPOSAL_CREATED"
PROPOSAL_FUNDED = "PROPOSAL_FUNDED"
PEER_REVIEW_CREATED = "PEER_REVIEW_CREATED"
COMMENT_CREATED = "COMMENT_CREATED"
ITEM_UPVOTED = "ITEM_UPVOTED"
PREPRINT_SUBMITTED = "PREPRINT_SUBMITTED"

# Event Weights (values for Personalize)
# These values represent the importance/weight of each event type
EVENT_WEIGHTS = {
    BOUNTY_SOLUTION_SUBMITTED: 2.0,
    BOUNTY_SOLUTION_AWARDED: 3.0,
    BOUNTY_CREATED: 3.0,
    BOUNTY_CONTRIBUTED: 2.0,
    RFP_CREATED: 3.0,
    RFP_APPLIED: 3.0,
    PROPOSAL_CREATED: 3.0,
    PROPOSAL_FUNDED: 3.0,
    PEER_REVIEW_CREATED: 2.5,
    COMMENT_CREATED: 1.5,
    ITEM_UPVOTED: 1.0,
    PREPRINT_SUBMITTED: 2.0,
}

# Event Type Configurations
# Each event type can be enabled/disabled and maps to a specific mapper
EVENT_TYPE_CONFIGS = {
    "bounty_solution": {
        "enabled": True,
        "mapper_class": "BountySolutionMapper",
        "description": "Bounty solution submissions and awards",
    },
    "bounty": {
        "enabled": True,
        "mapper_class": "BountyMapper",
        "description": "Bounty creation events",
    },
    "bounty_contribution": {
        "enabled": True,
        "mapper_class": "BountyContributionMapper",
        "description": "Bounty contribution events (adding funds to existing bounties)",
    },
    "rfp": {
        "enabled": True,
        "mapper_class": "RfpMapper",
        "description": "Request for Proposal (Grant) creation events",
    },
    "rfp_application": {
        "enabled": True,
        "mapper_class": "RfpApplicationMapper",
        "description": "Grant application (RFP application) events",
    },
    "proposal": {
        "enabled": True,
        "mapper_class": "ProposalMapper",
        "description": "Proposal (Preregistration) creation events",
    },
    "proposal_funding": {
        "enabled": True,
        "mapper_class": "ProposalFundingMapper",
        "description": "Proposal funding events (fundraise contributions)",
    },
    "peer_review": {
        "enabled": True,
        "mapper_class": "PeerReviewMapper",
        "description": "Peer review creation events",
    },
    "comment": {
        "enabled": True,
        "mapper_class": "CommentMapper",
        "description": (
            "Comment creation events (GENERIC_COMMENT only, excludes bounties)"
        ),
    },
    "upvote": {
        "enabled": True,
        "mapper_class": "UpvoteMapper",
        "description": "Item upvote events (papers, posts, comments)",
    },
    "preprint": {
        "enabled": True,
        "mapper_class": "PreprintMapper",
        "description": "Preprint submission events (user-uploaded papers)",
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
