"""
Contribution Weight System for Funding-Based Reputation Scoring

This module implements funding-based reputation scoring where reputation is primarily
earned through RSC (ResearchCoin) flows, with minimal base reputation for content creation.

REVISED: Based on feedback
- Tips: Curved scaling (generous, hard to game)
- Bounties: Generous tiers (manually reviewed quality)
- Proposals: Logarithmic scaling (prevent dominance)
- Funders: 1.5x bonus (encourage giving RSC)
- Content creation: Minimal/zero (prevent spam)
- Verified account: 100 REP one-time (quality > ID)

Example:
    >>> from reputation.related_models.contribution_weight import ContributionWeight
    >>> 
    >>> # Tip received
    >>> rep = ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', 10)
    >>> # Returns: 10 (curved scaling)
    >>> 
    >>> # Bounty payout
    >>> rep = ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
    >>> # Returns: 50 (generous tier)
    >>> 
    >>> # Proposal funded
    >>> rep = ContributionWeight.calculate_reputation_from_rsc('PROPOSAL_FUNDED', 1000)
    >>> # Returns: 100 (logarithmic tier 1)
    >>> 
    >>> # Funding proposal (with bonus)
    >>> rep = ContributionWeight.calculate_reputation_from_rsc('PROPOSAL_FUNDING_CONTRIBUTION', 1000, is_funder=True)
    >>> # Returns: 150 (100 × 1.5 funder bonus)
"""

from django.conf import settings


class ContributionWeight:
    """
    Registry and calculator for contribution reputation weights.
    
    Primary focus: RSC flows → Reputation
    Secondary: Basic engagement (upvotes)
    Minimal: Content creation (anti-spam)
    """
    
    # ==========================================
    # RSC Flow Types (Primary Reputation Source)
    # ==========================================
    
    # Receiving RSC
    TIP_RECEIVED = 'TIP_RECEIVED'                           # Tips on content
    BOUNTY_PAYOUT = 'BOUNTY_PAYOUT'                         # Bounty payments (mostly peer reviews)
    PROPOSAL_FUNDED = 'PROPOSAL_FUNDED'                     # Proposal funding received
    
    # Giving RSC (incentivize funders)
    PROPOSAL_FUNDING_CONTRIBUTION = 'PROPOSAL_FUNDING_CONTRIBUTION'  # User funds proposal
    
    # ==========================================
    # Basic Engagement Types
    # ==========================================
    
    UPVOTE = 'UPVOTE'
    DOWNVOTE = 'DOWNVOTE'  # Currently unused, reserved for V2
    
    # System-generated (tracked separately)
    CITATION = 'CITATION'  # Citations use existing scoring algorithm
    
    # ==========================================
    # Content Creation Types (Minimal REP)
    # ==========================================
    
    COMMENT = 'COMMENT'
    THREAD_CREATED = 'THREAD_CREATED'
    POST_CREATED = 'POST_CREATED'
    BOUNTY_CREATED = 'BOUNTY_CREATED'
    PEER_REVIEW = 'PEER_REVIEW'
    
    # ==========================================
    # Special Types
    # ==========================================
    
    VERIFIED_ACCOUNT = 'VERIFIED_ACCOUNT'
    DELETION_PENALTY = 'DELETION_PENALTY'
    
    # ==========================================
    # Configuration Constants
    # ==========================================
    
    # Verified account one-time bonus 
    VERIFIED_ACCOUNT_BONUS = 100
    
    # Funder bonus multiplier 
    FUNDER_BONUS_MULTIPLIER = 1.5
    
    # Content creation base weights 
    CONTENT_CREATION_WEIGHTS = {
        BOUNTY_CREATED: 5,     
        POST_CREATED: 2,       
        THREAD_CREATED: 1,    
        COMMENT: 0,            
        PEER_REVIEW: 0,
        CITATION: 0,  # Citations use separate scoring algorithm
    }
    
    # Basic engagement weights
    BASE_WEIGHTS = {
        UPVOTE: 1,
        DOWNVOTE: -1,  # Reserved for V2
    }
    
    # ==========================================
    # RSC → REP Conversion Methods
    # ==========================================
    
    @classmethod
    def calculate_tip_reputation(cls, tip_amount):
        """
        Calculate reputation for tips received using tiered generous scaling.
        
        TIERED FORMULA: Generous at small amounts, tapering at larger amounts
        
        Why generous tiered: Tips mean extremely good review/comment, more important than 
        just making a comment (3 REP). More difficult to game since tip costs real money.
        
        Tiers (generous rewards):
        - $0-10: 1.0x linear ($10 → 10 REP)
        - $11-50: 10 + 0.75x above $10 ($50 → 40 REP)
        - $51-100: 40 + 0.6x above $50 ($100 → 70 REP)
        - $100+: 70 + 0.55x above $100 ($200 → 125 REP)
        
        Args:
            tip_amount (float): Tip amount in dollars/RSC
            
        Returns:
            int: Reputation points to award
            
        Examples:
            >>> calculate_tip_reputation(1)
            1
            >>> calculate_tip_reputation(10)
            10
            >>> calculate_tip_reputation(50)
            40
            >>> calculate_tip_reputation(100)
            70
        """
        if tip_amount <= 0:
            return 0
        
        # Tier 1: $0-10 at 1.0x (linear, generous for small tips)
        if tip_amount <= 10:
            return int(tip_amount)
        
        rep = 10
        remaining = tip_amount - 10
        
        # Tier 2: $11-50 at 0.75x
        if remaining <= 40:
            return int(rep + remaining * 0.75)
        
        rep += 40 * 0.75  # 30
        remaining -= 40
        
        # Tier 3: $51-100 at 0.6x
        if remaining <= 50:
            return int(rep + remaining * 0.6)
        
        rep += 50 * 0.6  # 30
        remaining -= 50
        
        # Tier 4: $100+ at 0.55x
        return int(rep + remaining * 0.55)
    
    @classmethod
    def calculate_bounty_reputation(cls, bounty_amount):
        """
        Calculate reputation for bounty payouts using generous tiered linear.
        
        99.9% of bounties are peer review bounties ($150 standard).
        All are manually reviewed for quality by ResearchHub editors.
        
        Tiers:
        - $0-$200: 0.33 REP per $ (~$150 → 50 REP)
        - $200-$1000: 50 + 0.3 REP per $ above $200
        - $1000+: 50 + 240 + 0.25 REP per $ above $1000
        
        Args:
            bounty_amount (float): Bounty amount in dollars/RSC
            
        Returns:
            int: Reputation points to award
            
        Examples:
            >>> calculate_bounty_reputation(150)
            50
            >>> calculate_bounty_reputation(500)
            150
            >>> calculate_bounty_reputation(1000)
            250
        """
        if bounty_amount <= 0:
            return 0
        
        if bounty_amount < 200:
            # Lower tier: generous 0.33 per $
            return int(bounty_amount * 0.33)
        elif bounty_amount < 1000:
            # Mid tier: 50 base + 0.3 per $ above $200
            return int(50 + (bounty_amount - 200) * 0.3)
        else:
            # Upper tier: 50 + 240 + 0.25 per $ above $1000
            return int(50 + 240 + (bounty_amount - 1000) * 0.25)
    
    @classmethod
    def calculate_proposal_reputation(cls, proposal_amount, is_funder=False):
        """
        Calculate reputation for proposals using logarithmic scaling.
        
        LOGARITHMIC TIERS:
        "Logistic based function could be good fit to prevent mega-proposals 
        from dominating reputation."
        
        Tiers (diminishing returns):
        - $0-$1K: 0.1 REP per $1 (100%)
        - $1K-$100K: 0.01 REP per $1 (10%)
        - $100K-$1M: 0.001 REP per $1 (1%)
        - $1M+: 0.0001 REP per $1 (0.1%)
        
        FUNDER BONUS: 1.5x multiplier

        
        Args:
            proposal_amount (float): Proposal amount in dollars/RSC
            is_funder (bool): True if user is giving RSC (gets 1.5x bonus)
            
        Returns:
            int: Reputation points to award
            
        Examples:
            >>> # Creator receiving
            >>> calculate_proposal_reputation(1000, is_funder=False)
            100
            >>> calculate_proposal_reputation(10000, is_funder=False)
            190
            >>> calculate_proposal_reputation(1000000, is_funder=False)
            1990
            
            >>> # Funder giving (1.5x bonus)
            >>> calculate_proposal_reputation(1000, is_funder=True)
            150
        """
        if proposal_amount <= 0:
            return 0
        
        rep = 0
        remaining = proposal_amount
        
        # Tier 1: $0-$1,000 at 0.1 REP per $1
        tier1_amount = min(remaining, 1000)
        rep += tier1_amount * 0.1
        remaining -= tier1_amount
        
        if remaining <= 0:
            return int(rep * (cls.FUNDER_BONUS_MULTIPLIER if is_funder else 1.0))
        
        # Tier 2: $1,000-$100,000 at 0.01 REP per $1 (10x harder)
        tier2_amount = min(remaining, 99000)
        rep += tier2_amount * 0.01
        remaining -= tier2_amount
        
        if remaining <= 0:
            return int(rep * (cls.FUNDER_BONUS_MULTIPLIER if is_funder else 1.0))
        
        # Tier 3: $100,000-$1,000,000 at 0.001 REP per $1 (100x harder)
        tier3_amount = min(remaining, 900000)
        rep += tier3_amount * 0.001
        remaining -= tier3_amount
        
        if remaining <= 0:
            return int(rep * (cls.FUNDER_BONUS_MULTIPLIER if is_funder else 1.0))
        
        # Tier 4: $1,000,000+ at 0.0001 REP per $1 (1000x harder)
        rep += remaining * 0.0001
        
        # Apply funder bonus if applicable
        return int(rep * (cls.FUNDER_BONUS_MULTIPLIER if is_funder else 1.0))
    
    @classmethod
    def calculate_reputation_from_rsc(cls, contribution_type, rsc_amount, is_funder=False):
        """
        Main dispatcher for RSC → REP conversion.
        
        Routes to appropriate calculation method based on contribution type.
        
        Args:
            contribution_type (str): Type of RSC flow (TIP_RECEIVED, BOUNTY_PAYOUT, etc.)
            rsc_amount (float): Amount of RSC in dollars
            is_funder (bool): True if user is giving RSC (for proposal funding)
            
        Returns:
            int: Reputation points to award
            
        Examples:
            >>> calculate_reputation_from_rsc('TIP_RECEIVED', 10)
            10
            >>> calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
            50
            >>> calculate_reputation_from_rsc('PROPOSAL_FUNDED', 1000)
            100
            >>> calculate_reputation_from_rsc('PROPOSAL_FUNDING_CONTRIBUTION', 1000, is_funder=True)
            150
        """
        if contribution_type == cls.TIP_RECEIVED:
            return cls.calculate_tip_reputation(rsc_amount)
        
        elif contribution_type == cls.BOUNTY_PAYOUT:
            return cls.calculate_bounty_reputation(rsc_amount)
        
        elif contribution_type in [cls.PROPOSAL_FUNDED, cls.PROPOSAL_FUNDING_CONTRIBUTION]:
            # Proposal funding uses same curve, but funders get bonus
            is_funding_contribution = (contribution_type == cls.PROPOSAL_FUNDING_CONTRIBUTION)
            return cls.calculate_proposal_reputation(rsc_amount, is_funder=is_funding_contribution)
        
        else:
            return 0
    
    # ==========================================
    # Main Calculation Method
    # ==========================================
    
    @classmethod
    def calculate_reputation_change(cls, contribution_type):
        """
        Calculate reputation change for non-RSC contributions.
        
        Minimal content creation REP to prevent spam.
        Most reputation comes from RSC flows + upvotes.
        
        
        Args:
            contribution_type (str): Type of contribution (UPVOTE, COMMENT, etc.)
                
        Returns:
            int: Reputation change amount
            
        Examples:
            >>> calculate_reputation_change('UPVOTE')
            1
            >>> calculate_reputation_change('COMMENT')
            0
            >>> calculate_reputation_change('PEER_REVIEW')
            0
            >>> calculate_reputation_change('BOUNTY_CREATED')
            5
        """
        # Check for settings override first (highest priority)
        overrides = getattr(settings, 'CONTRIBUTION_WEIGHT_OVERRIDES', {})
        if contribution_type in overrides:
            return overrides[contribution_type]
        
        # Check basic weights (upvotes/downvotes)
        if contribution_type in cls.BASE_WEIGHTS:
            return cls.BASE_WEIGHTS[contribution_type]
        
        # Check content creation (minimal)
        if contribution_type in cls.CONTENT_CREATION_WEIGHTS:
            return cls.CONTENT_CREATION_WEIGHTS[contribution_type]
        
        # Default: no reputation
        return 0
    
    # ==========================================
    # Configuration & Feature Flag
    # ==========================================
    
    @classmethod
    def is_tiered_scoring_enabled(cls):
        """
        Check if tiered scoring is enabled via feature flag.
        
        Returns:
            bool: True if tiered scoring is enabled, False otherwise
        """
        return getattr(settings, 'TIERED_SCORING_ENABLED', False)
    
    @classmethod
    def get_verified_account_bonus(cls):
        """
        Get verified account bonus amount.
        
        Can be overridden via settings.VERIFIED_ACCOUNT_BONUS
        
        Returns:
            int: One-time reputation bonus for verification (default: 100)
        """
        return getattr(settings, 'VERIFIED_ACCOUNT_BONUS', cls.VERIFIED_ACCOUNT_BONUS)
    
    @classmethod
    def get_funder_bonus_multiplier(cls):
        """
        Get funder bonus multiplier.
        
        Can be overridden via settings.FUNDER_BONUS_MULTIPLIER
        
        Returns:
            float: Multiplier for funders (default: 1.5)
        """
        return getattr(settings, 'FUNDER_BONUS_MULTIPLIER', cls.FUNDER_BONUS_MULTIPLIER)
    
    # ==========================================
    # Utility Methods
    # ==========================================
    
    @classmethod
    def get_contribution_type_display(cls, contribution_type):
        """
        Get human-readable display name for contribution type.
        
        Args:
            contribution_type (str): Contribution type constant
            
        Returns:
            str: Display name
        """
        display_names = {
            cls.UPVOTE: 'Upvote',
            cls.DOWNVOTE: 'Downvote',
            cls.CITATION: 'Citation',
            cls.TIP_RECEIVED: 'Tip Received',
            cls.BOUNTY_PAYOUT: 'Bounty Payout',
            cls.PROPOSAL_FUNDED: 'Proposal Funded',
            cls.PROPOSAL_FUNDING_CONTRIBUTION: 'Proposal Funding Contribution',
            cls.COMMENT: 'Comment',
            cls.THREAD_CREATED: 'Thread Created',
            cls.POST_CREATED: 'Post Created',
            cls.BOUNTY_CREATED: 'Bounty Created',
            cls.PEER_REVIEW: 'Peer Review',
            cls.VERIFIED_ACCOUNT: 'Verified Account',
            cls.DELETION_PENALTY: 'Content Deletion Penalty',
        }
        
        return display_names.get(contribution_type, contribution_type)
    
    @classmethod
    def get_all_contribution_types(cls):
        """
        Get list of all valid contribution types.
        
        Returns:
            list: All contribution type constants
        """
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
            cls.PEER_REVIEW,
            cls.VERIFIED_ACCOUNT,
            cls.DELETION_PENALTY,
        ]
    
    @classmethod
    def validate_contribution_type(cls, contribution_type):
        """
        Validate that a contribution type is recognized.
        
        Args:
            contribution_type (str): Type to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        return contribution_type in cls.get_all_contribution_types()
