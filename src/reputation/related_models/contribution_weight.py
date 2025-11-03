"""
Contribution Weight System for Tiered Reputation Scoring

This module implements weighted reputation scoring where different contribution
types receive different reputation amounts based on effort and complexity.

Example:
    >>> from reputation.related_models.contribution_weight import ContributionWeight
    >>> 
    >>> # Simple upvote
    >>> rep = ContributionWeight.calculate_reputation_change('UPVOTE')
    >>> # Returns: 1
    >>> 
    >>> # Peer review
    >>> rep = ContributionWeight.calculate_reputation_change('PEER_REVIEW')
    >>> # Returns: 15
"""

from django.conf import settings


class ContributionWeight:
    """
    Registry and calculator for contribution reputation weights.
    
    This class defines base weights for different contribution types.
    
    Attributes:
        All contribution type constants (UPVOTE, COMMENT, PEER_REVIEW, etc.)
        BASE_WEIGHTS: Dict mapping contribution types to base reputation values
    """
    
    # ==========================================
    # Contribution Type Constants
    # ==========================================
    
    # Low effort, high volume
    UPVOTE = 'UPVOTE'
    DOWNVOTE = 'DOWNVOTE'
    
    # System-generated (not user actions)
    CITATION = 'CITATION'
    
    # Medium effort
    COMMENT = 'COMMENT'
    THREAD_CREATED = 'THREAD_CREATED'
    BOUNTY_CREATED = 'BOUNTY_CREATED'
    POST_CREATED = 'POST_CREATED'
    
    # High effort
    PEER_REVIEW = 'PEER_REVIEW'
    BOUNTY_SOLUTION = 'BOUNTY_SOLUTION'
    
    # Exceptional effort
    PAPER_PUBLISHED = 'PAPER_PUBLISHED'
    BOUNTY_FUNDED = 'BOUNTY_FUNDED'
    
    # ==========================================
    # Base Weights
    # ==========================================
    
    BASE_WEIGHTS = {
        # Low effort (1x)
        UPVOTE: 1,
        DOWNVOTE: 1,
        
        # System-generated (tracked but calculated separately)
        CITATION: 0,  # Citations use their own scoring algorithm
        
        # Medium effort (3-10x)
        COMMENT: 3,
        THREAD_CREATED: 5,
        BOUNTY_CREATED: 5,
        POST_CREATED: 10,
        
        # High effort (15-20x)
        PEER_REVIEW: 15,
        BOUNTY_SOLUTION: 20,
        
        # Exceptional effort (30-50x)
        BOUNTY_FUNDED: 30,
        PAPER_PUBLISHED: 50,
    }
    
    # ==========================================
    # Configuration Methods
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
    def get_base_weight(cls, contribution_type):
        """
        Get base weight for a contribution type.
        
        Can be overridden via settings.CONTRIBUTION_WEIGHT_OVERRIDES
        
        Args:
            contribution_type (str): The type of contribution
            
        Returns:
            int: Base reputation weight for this contribution type
        """
        overrides = getattr(settings, 'CONTRIBUTION_WEIGHT_OVERRIDES', {})
        
        if contribution_type in overrides:
            return overrides[contribution_type]
        
        return cls.BASE_WEIGHTS.get(contribution_type, 1)
    
    # ==========================================
    # Core Calculation Methods
    # ==========================================
    
    @classmethod
    def calculate_reputation_change(cls, contribution_type, contribution_context=None):
        """
        Calculate reputation change for a contribution.
        
        This is the main entry point for calculating how much reputation
        a user should receive for a given contribution.
        
        Args:
            contribution_type (str): Type of contribution (UPVOTE, COMMENT, etc.)
            contribution_context (dict, optional): Unused, kept for API compatibility
                
        Returns:
            int: Reputation change amount based on contribution type
            
        Examples:
            >>> # Simple upvote
            >>> calculate_reputation_change('UPVOTE')
            1
            
            >>> # Comment
            >>> calculate_reputation_change('COMMENT')
            3
            
            >>> # Peer review
            >>> calculate_reputation_change('PEER_REVIEW')
            15
        """
        # Get base weight (this is the only reputation value now)
        return cls.get_base_weight(contribution_type)
    
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
            cls.COMMENT: 'Comment',
            cls.THREAD_CREATED: 'Thread Created',
            cls.BOUNTY_CREATED: 'Bounty Created',
            cls.POST_CREATED: 'Post Created',
            cls.PEER_REVIEW: 'Peer Review',
            cls.BOUNTY_SOLUTION: 'Bounty Solution',
            cls.BOUNTY_FUNDED: 'High-Value Bounty',
            cls.PAPER_PUBLISHED: 'Paper Published',
        }
        
        return display_names.get(contribution_type, contribution_type)
    
    @classmethod
    def get_all_contribution_types(cls):
        """
        Get list of all valid contribution types.
        
        Returns:
            list: All contribution type constants
        """
        return list(cls.BASE_WEIGHTS.keys())
    
    @classmethod
    def validate_contribution_type(cls, contribution_type):
        """
        Validate that a contribution type is recognized.
        
        Args:
            contribution_type (str): Type to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        return contribution_type in cls.BASE_WEIGHTS

