from django.conf import settings


class ContributionWeight:
    TIP_RECEIVED = "TIP_RECEIVED"
    BOUNTY_PAYOUT = "BOUNTY_PAYOUT"
    PROPOSAL_FUNDED = "PROPOSAL_FUNDED"
    PROPOSAL_FUNDING_CONTRIBUTION = "PROPOSAL_FUNDING_CONTRIBUTION"

    UPVOTE = "UPVOTE"
    DOWNVOTE = "DOWNVOTE"
    CITATION = "CITATION"

    COMMENT = "COMMENT"
    THREAD_CREATED = "THREAD_CREATED"
    POST_CREATED = "POST_CREATED"
    BOUNTY_CREATED = "BOUNTY_CREATED"
    BOUNTY_SOLUTION = "BOUNTY_SOLUTION"
    BOUNTY_FUNDED = "BOUNTY_FUNDED"
    PEER_REVIEW = "PEER_REVIEW"
    PAPER_PUBLISHED = "PAPER_PUBLISHED"

    VERIFIED_ACCOUNT = "VERIFIED_ACCOUNT"
    DELETION_PENALTY = "DELETION_PENALTY"

    VERIFIED_ACCOUNT_BONUS = 100
    FUNDER_BONUS_MULTIPLIER = 1.5

    CONTENT_CREATION_WEIGHTS = {
        BOUNTY_CREATED: 5,
        BOUNTY_FUNDED: 5,
        POST_CREATED: 2,
        PAPER_PUBLISHED: 2,
        THREAD_CREATED: 1,
        COMMENT: 0,
        PEER_REVIEW: 0,
        BOUNTY_SOLUTION: 0,
        CITATION: 0,
    }

    BASE_WEIGHTS = {
        UPVOTE: 1,
        DOWNVOTE: -1,
    }

    @classmethod
    def calculate_tip_reputation(cls, tip_amount):
        if tip_amount <= 0:
            return 0

        if tip_amount <= 10:
            return int(tip_amount)

        rep = 10
        remaining = tip_amount - 10

        if remaining <= 40:
            return int(rep + remaining * 0.75)

        rep += 40 * 0.75
        remaining -= 40

        if remaining <= 50:
            return int(rep + remaining * 0.6)

        rep += 50 * 0.6
        remaining -= 50

        return int(rep + remaining * 0.55)

    @classmethod
    def calculate_bounty_reputation(cls, bounty_amount):
        if bounty_amount <= 0:
            return 0

        if bounty_amount < 200:
            return int(bounty_amount * 0.33)
        elif bounty_amount < 1000:
            return int(50 + (bounty_amount - 200) * 0.3)
        else:
            return int(50 + 240 + (bounty_amount - 1000) * 0.25)

    @classmethod
    def calculate_proposal_reputation(cls, proposal_amount, is_funder=False):
        if proposal_amount <= 0:
            return 0

        rep = 0
        remaining = proposal_amount

        tier1_amount = min(remaining, 1000)
        rep += tier1_amount * 0.1
        remaining -= tier1_amount

        if remaining <= 0:
            return int(rep * (cls.FUNDER_BONUS_MULTIPLIER if is_funder else 1.0))

        tier2_amount = min(remaining, 99000)
        rep += tier2_amount * 0.01
        remaining -= tier2_amount

        if remaining <= 0:
            return int(rep * (cls.FUNDER_BONUS_MULTIPLIER if is_funder else 1.0))

        tier3_amount = min(remaining, 900000)
        rep += tier3_amount * 0.001
        remaining -= tier3_amount

        if remaining <= 0:
            return int(rep * (cls.FUNDER_BONUS_MULTIPLIER if is_funder else 1.0))

        rep += remaining * 0.0001

        return int(rep * (cls.FUNDER_BONUS_MULTIPLIER if is_funder else 1.0))

    @classmethod
    def calculate_reputation_from_rsc(
        cls, contribution_type, rsc_amount, is_funder=False
    ):
        if contribution_type == cls.TIP_RECEIVED:
            return cls.calculate_tip_reputation(rsc_amount)

        elif contribution_type == cls.BOUNTY_PAYOUT:
            return cls.calculate_bounty_reputation(rsc_amount)

        elif contribution_type in [
            cls.PROPOSAL_FUNDED,
            cls.PROPOSAL_FUNDING_CONTRIBUTION,
        ]:
            is_funding_contribution = (
                contribution_type == cls.PROPOSAL_FUNDING_CONTRIBUTION
            )
            return cls.calculate_proposal_reputation(
                rsc_amount, is_funder=is_funding_contribution
            )

        else:
            return 0

    @classmethod
    def calculate_reputation_change(cls, contribution_type):
        overrides = getattr(settings, "CONTRIBUTION_WEIGHT_OVERRIDES", {})
        if contribution_type in overrides:
            return overrides[contribution_type]

        if contribution_type in cls.BASE_WEIGHTS:
            return cls.BASE_WEIGHTS[contribution_type]

        if contribution_type in cls.CONTENT_CREATION_WEIGHTS:
            return cls.CONTENT_CREATION_WEIGHTS[contribution_type]

        return 0

    @classmethod
    def is_tiered_scoring_enabled(cls):
        return getattr(settings, "TIERED_SCORING_ENABLED", False)

    @classmethod
    def get_verified_account_bonus(cls):
        return getattr(settings, "VERIFIED_ACCOUNT_BONUS", cls.VERIFIED_ACCOUNT_BONUS)

    @classmethod
    def get_funder_bonus_multiplier(cls):
        return getattr(settings, "FUNDER_BONUS_MULTIPLIER", cls.FUNDER_BONUS_MULTIPLIER)

    @classmethod
    def get_contribution_type_display(cls, contribution_type):
        display_names = {
            cls.UPVOTE: "Upvote",
            cls.DOWNVOTE: "Downvote",
            cls.CITATION: "Citation",
            cls.TIP_RECEIVED: "Tip Received",
            cls.BOUNTY_PAYOUT: "Bounty Payout",
            cls.PROPOSAL_FUNDED: "Proposal Funded",
            cls.PROPOSAL_FUNDING_CONTRIBUTION: "Proposal Funding Contribution",
            cls.COMMENT: "Comment",
            cls.THREAD_CREATED: "Thread Created",
            cls.POST_CREATED: "Post Created",
            cls.BOUNTY_CREATED: "Bounty Created",
            cls.BOUNTY_SOLUTION: "Bounty Solution",
            cls.BOUNTY_FUNDED: "Bounty Funded",
            cls.PEER_REVIEW: "Peer Review",
            cls.PAPER_PUBLISHED: "Paper Published",
            cls.VERIFIED_ACCOUNT: "Verified Account",
            cls.DELETION_PENALTY: "Content Deletion Penalty",
        }

        return display_names.get(contribution_type, contribution_type)

    @classmethod
    def get_all_contribution_types(cls):
        return [
            cls.TIP_RECEIVED,
            cls.BOUNTY_PAYOUT,
            cls.PROPOSAL_FUNDED,
            cls.PROPOSAL_FUNDING_CONTRIBUTION,
            cls.UPVOTE,
            cls.DOWNVOTE,
            cls.CITATION,
            cls.COMMENT,
            cls.THREAD_CREATED,
            cls.POST_CREATED,
            cls.BOUNTY_CREATED,
            cls.BOUNTY_SOLUTION,
            cls.BOUNTY_FUNDED,
            cls.PEER_REVIEW,
            cls.PAPER_PUBLISHED,
            cls.VERIFIED_ACCOUNT,
            cls.DELETION_PENALTY,
        ]

    @classmethod
    def validate_contribution_type(cls, contribution_type):
        return contribution_type in cls.get_all_contribution_types()
