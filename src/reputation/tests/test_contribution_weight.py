"""
Unit tests for ContributionWeight system (Funding-Based).

REVISED: Based on community feedback from Dominikus, Scott, Ruslan, Xavier
- Tips use curved scaling (generous, hard to game)
- Bounties use generous tiers (manually reviewed)
- Proposals use logarithmic scaling (prevent dominance)
- Funders get 1.5x bonus (encourage giving RSC)
- Content creation minimal/zero (prevent spam)
- Verified account 100 REP (quality > ID)

Tests cover:
- RSC → REP conversion (tips, bounties, proposals)
- Curved and logarithmic formulas
- Funder bonus
- Content creation weights (minimal)
- Feature flags
- Edge cases
"""

from django.test import TestCase, override_settings

from reputation.related_models.contribution_weight import ContributionWeight


class TipReputationTests(TestCase):
    """Test curved scaling for tips."""
    
    def test_tip_curved_scaling(self):
        """Tips should use curved formula (amount^0.85)."""
        test_cases = [
            (1, 1),
            (5, 5),
            (10, 10),
            (50, 40),
            (100, 70),
            (200, 125),
        ]
        
        for tip_amount, expected_rep in test_cases:
            with self.subTest(tip_amount=tip_amount):
                rep = ContributionWeight.calculate_tip_reputation(tip_amount)
                # Allow ±1 for rounding
                self.assertAlmostEqual(rep, expected_rep, delta=1)
    
    def test_tip_zero_amount(self):
        """Zero tip should return 0 REP."""
        rep = ContributionWeight.calculate_tip_reputation(0)
        self.assertEqual(rep, 0)
    
    def test_tip_negative_amount(self):
        """Negative tip should return 0 REP."""
        rep = ContributionWeight.calculate_tip_reputation(-10)
        self.assertEqual(rep, 0)
    
    def test_tip_via_main_method(self):
        """Tips should work via calculate_reputation_from_rsc."""
        rep = ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', 10)
        self.assertEqual(rep, 10)


class BountyReputationTests(TestCase):
    """Test generous tiered scaling for bounty payouts."""
    
    def test_bounty_tier_1(self):
        """Bounties under $200 use 0.33 multiplier."""
        # $150 standard peer review bounty
        rep = ContributionWeight.calculate_bounty_reputation(150)
        self.assertEqual(rep, 49)  # 150 * 0.33 = 49.5 → 49
    
    def test_bounty_tier_2(self):
        """Bounties $200-$1000 use tiered formula."""
        rep = ContributionWeight.calculate_bounty_reputation(500)
        # 50 + (500-200) * 0.3 = 50 + 90 = 140
        self.assertAlmostEqual(rep, 140, delta=2)
    
    def test_bounty_tier_3(self):
        """Bounties over $1000 use upper tier."""
        rep = ContributionWeight.calculate_bounty_reputation(2000)
        # 50 + 240 + (2000-1000) * 0.25 = 50 + 240 + 250 = 540
        self.assertAlmostEqual(rep, 540, delta=5)
    
    def test_bounty_zero_amount(self):
        """Zero bounty should return 0 REP."""
        rep = ContributionWeight.calculate_bounty_reputation(0)
        self.assertEqual(rep, 0)
    
    def test_bounty_via_main_method(self):
        """Bounties should work via calculate_reputation_from_rsc."""
        rep = ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
        self.assertAlmostEqual(rep, 50, delta=2)


class ProposalReputationTests(TestCase):
    """Test logarithmic scaling for proposals."""
    
    def test_proposal_tier_1(self):
        """Proposals under $1K use 0.1 per $."""
        rep = ContributionWeight.calculate_proposal_reputation(1000, is_funder=False)
        self.assertEqual(rep, 100)  # 1000 * 0.1
    
    def test_proposal_tier_2(self):
        """Proposals $1K-$100K use logarithmic scaling."""
        rep = ContributionWeight.calculate_proposal_reputation(10000, is_funder=False)
        # Tier 1: 1000 * 0.1 = 100
        # Tier 2: 9000 * 0.01 = 90
        # Total: 190
        self.assertEqual(rep, 190)
    
    def test_proposal_tier_3(self):
        """Proposals $100K-$1M use further diminished scaling."""
        rep = ContributionWeight.calculate_proposal_reputation(100000, is_funder=False)
        # Tier 1: 1000 * 0.1 = 100
        # Tier 2: 99000 * 0.01 = 990
        # Tier 3: 0
        # Total: 1090
        self.assertEqual(rep, 1090)
    
    def test_proposal_mega(self):
        """Mega proposals use tier 4 (ultra-diminished)."""
        rep = ContributionWeight.calculate_proposal_reputation(1000000, is_funder=False)
        # Tier 1: 1000 * 0.1 = 100
        # Tier 2: 99000 * 0.01 = 990
        # Tier 3: 900000 * 0.001 = 900
        # Total: 1990
        self.assertEqual(rep, 1990)
    
    def test_proposal_funder_bonus(self):
        """Funders should get 1.5x bonus."""
        rep_receiver = ContributionWeight.calculate_proposal_reputation(1000, is_funder=False)
        rep_funder = ContributionWeight.calculate_proposal_reputation(1000, is_funder=True)
        
        self.assertEqual(rep_receiver, 100)
        self.assertEqual(rep_funder, 150)  # 100 * 1.5
    
    def test_proposal_funder_bonus_large_amount(self):
        """Funder bonus should apply to all tiers."""
        rep_receiver = ContributionWeight.calculate_proposal_reputation(100000, is_funder=False)
        rep_funder = ContributionWeight.calculate_proposal_reputation(100000, is_funder=True)
        
        self.assertEqual(rep_receiver, 1090)
        self.assertEqual(rep_funder, 1635)  # 1090 * 1.5
    
    def test_proposal_via_main_method(self):
        """Proposals should work via calculate_reputation_from_rsc."""
        rep = ContributionWeight.calculate_reputation_from_rsc('PROPOSAL_FUNDED', 1000)
        self.assertEqual(rep, 100)


class ContentCreationTests(TestCase):
    """Test minimal/zero reputation for content creation (anti-spam)."""
    
    def test_comment_zero_rep(self):
        """Comments should give 0 base REP (get REP from tips/votes instead)."""
        rep = ContributionWeight.calculate_reputation_change('COMMENT')
        self.assertEqual(rep, 0)
    
    def test_peer_review_zero_rep(self):
        """Peer reviews should give 0 base REP (get REP from bounty payouts)."""
        rep = ContributionWeight.calculate_reputation_change('PEER_REVIEW')
        self.assertEqual(rep, 0)
    
    def test_thread_minimal_rep(self):
        """Threads should give minimal REP (reduced from 5 to 1)."""
        rep = ContributionWeight.calculate_reputation_change('THREAD_CREATED')
        self.assertEqual(rep, 1)
    
    def test_post_minimal_rep(self):
        """Posts should give minimal REP (reduced from 10 to 2)."""
        rep = ContributionWeight.calculate_reputation_change('POST_CREATED')
        self.assertEqual(rep, 2)
    
    def test_bounty_created_keeps_rep(self):
        """Bounty creation keeps REP (funding research is good)."""
        rep = ContributionWeight.calculate_reputation_change('BOUNTY_CREATED')
        self.assertEqual(rep, 5)


class EngagementTests(TestCase):
    """Test basic engagement (upvotes/downvotes)."""
    
    def test_upvote_gives_one_rep(self):
        """Upvotes should give 1 REP."""
        rep = ContributionWeight.calculate_reputation_change('UPVOTE')
        self.assertEqual(rep, 1)
    
    def test_downvote_negative_rep(self):
        """Downvotes should give -1 REP (reserved for V2)."""
        rep = ContributionWeight.calculate_reputation_change('DOWNVOTE')
        self.assertEqual(rep, -1)


class VerifiedAccountTests(TestCase):
    """Test verified account bonus."""
    
    def test_verified_account_bonus_default(self):
        """Verified account bonus should be 100 REP."""
        bonus = ContributionWeight.get_verified_account_bonus()
        self.assertEqual(bonus, 100)
    
    @override_settings(VERIFIED_ACCOUNT_BONUS=200)
    def test_verified_account_bonus_override(self):
        """Verified account bonus should be overridable."""
        bonus = ContributionWeight.get_verified_account_bonus()
        self.assertEqual(bonus, 200)


class FunderBonusTests(TestCase):
    """Test funder bonus multiplier."""
    
    def test_funder_bonus_default(self):
        """Funder bonus should be 1.5x."""
        multiplier = ContributionWeight.get_funder_bonus_multiplier()
        self.assertEqual(multiplier, 1.5)
    
    @override_settings(FUNDER_BONUS_MULTIPLIER=2.0)
    def test_funder_bonus_override(self):
        """Funder bonus should be overridable."""
        multiplier = ContributionWeight.get_funder_bonus_multiplier()
        self.assertEqual(multiplier, 2.0)


class FeatureFlagTests(TestCase):
    """Test feature flag behavior."""
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_feature_flag_enabled(self):
        """Feature flag should be readable from settings."""
        self.assertTrue(ContributionWeight.is_tiered_scoring_enabled())
    
    @override_settings(TIERED_SCORING_ENABLED=False)
    def test_feature_flag_disabled(self):
        """Feature flag disabled should return False."""
        self.assertFalse(ContributionWeight.is_tiered_scoring_enabled())
    
    def test_feature_flag_default(self):
        """Feature flag should default to False if not set."""
        self.assertFalse(ContributionWeight.is_tiered_scoring_enabled())


class UtilityMethodTests(TestCase):
    """Test utility methods."""
    
    def test_get_contribution_type_display(self):
        """Should return human-readable names."""
        self.assertEqual(
            ContributionWeight.get_contribution_type_display('UPVOTE'),
            'Upvote'
        )
        self.assertEqual(
            ContributionWeight.get_contribution_type_display('TIP_RECEIVED'),
            'Tip Received'
        )
        self.assertEqual(
            ContributionWeight.get_contribution_type_display('PROPOSAL_FUNDED'),
            'Proposal Funded'
        )
    
    def test_get_all_contribution_types(self):
        """Should return list of all contribution types."""
        types = ContributionWeight.get_all_contribution_types()
        
        self.assertIn('UPVOTE', types)
        self.assertIn('TIP_RECEIVED', types)
        self.assertIn('BOUNTY_PAYOUT', types)
        self.assertIn('PROPOSAL_FUNDED', types)
        self.assertIn('COMMENT', types)
    
    def test_validate_contribution_type_valid(self):
        """Should validate known contribution types."""
        self.assertTrue(ContributionWeight.validate_contribution_type('UPVOTE'))
        self.assertTrue(ContributionWeight.validate_contribution_type('TIP_RECEIVED'))
    
    def test_validate_contribution_type_invalid(self):
        """Should reject unknown contribution types."""
        self.assertFalse(ContributionWeight.validate_contribution_type('INVALID_TYPE'))


class EdgeCaseTests(TestCase):
    """Test edge cases and boundary conditions."""
    
    def test_rsc_amount_zero(self):
        """Zero RSC should return 0 REP."""
        rep = ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', 0)
        self.assertEqual(rep, 0)
    
    def test_rsc_amount_negative(self):
        """Negative RSC should return 0 REP."""
        rep = ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', -10)
        self.assertEqual(rep, 0)
    
    def test_unknown_rsc_type(self):
        """Unknown RSC type should return 0 REP."""
        rep = ContributionWeight.calculate_reputation_from_rsc('UNKNOWN_TYPE', 100)
        self.assertEqual(rep, 0)
    
    def test_unknown_contribution_type(self):
        """Unknown contribution type should return 0 REP."""
        rep = ContributionWeight.calculate_reputation_change('UNKNOWN_TYPE')
        self.assertEqual(rep, 0)


class RegressionTests(TestCase):
    """Regression tests for specific documented scenarios."""
    
    def test_quality_peer_reviewer_scenario(self):
        """Test the documented quality peer reviewer scenario."""
        # 10 peer reviews with $150 bounties
        bounty_rep = sum(
            ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
            for _ in range(10)
        )
        
        # Should be approximately 500 REP (10 × 50)
        self.assertAlmostEqual(bounty_rep, 500, delta=10)
    
    def test_generous_funder_scenario(self):
        """Test the documented generous funder scenario."""
        # Fund $5K across proposals (with 1.5x bonus)
        funding_rep = ContributionWeight.calculate_reputation_from_rsc(
            'PROPOSAL_FUNDING_CONTRIBUTION',
            5000,
            is_funder=True
        )
        
        # Tier 1: 1000 * 0.1 = 100
        # Tier 2: 4000 * 0.01 = 40
        # Total: 140 * 1.5 = 210
        self.assertAlmostEqual(funding_rep, 210, delta=10)
    
    def test_verified_vs_quality_work(self):
        """Quality work should be worth much more than just verification."""
        # Verified account
        verified_rep = ContributionWeight.VERIFIED_ACCOUNT_BONUS
        
        # Quality peer reviewer with 3 bounties
        quality_rep = sum(
            ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
            for _ in range(3)
        )
        
        # Quality work should be > verified
        self.assertGreater(quality_rep, verified_rep)
        # Specifically, ~150 REP (3×50) vs 100 REP
        self.assertGreater(quality_rep / verified_rep, 1.3)


class IntegrationTests(TestCase):
    """Integration tests combining multiple features."""
    
    def test_complete_user_journey(self):
        """Test a complete user journey with mixed contributions."""
        total_rep = 0
        
        # Get verified
        total_rep += ContributionWeight.VERIFIED_ACCOUNT_BONUS  # 100
        
        # Write 5 peer reviews, 3 get paid
        for _ in range(3):
            total_rep += ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)  # ~150
        
        # Receive 10 tips totaling $120
        total_rep += ContributionWeight.calculate_tip_reputation(120)  # ~80
        
        # Get 50 upvotes
        total_rep += 50 * ContributionWeight.calculate_reputation_change('UPVOTE')  # 50
        
        # Create 2 bounties
        total_rep += 2 * ContributionWeight.calculate_reputation_change('BOUNTY_CREATED')  # 10
        
        # Fund 1 proposal with $500
        total_rep += ContributionWeight.calculate_reputation_from_rsc(
            'PROPOSAL_FUNDING_CONTRIBUTION', 
            500, 
            is_funder=True
        )  # ~75
        
        # Total should be approximately: 100 + 150 + 80 + 50 + 10 + 75 = 465
        self.assertGreater(total_rep, 400)
        self.assertLess(total_rep, 500)
    
    def test_proposal_funding_both_sides(self):
        """Test proposal funding from both creator and funder perspective."""
        # Creator receives $10K
        creator_rep = ContributionWeight.calculate_reputation_from_rsc(
            'PROPOSAL_FUNDED',
            10000,
            is_funder=False
        )
        
        # Funder gives $10K (gets 1.5x bonus)
        funder_rep = ContributionWeight.calculate_reputation_from_rsc(
            'PROPOSAL_FUNDING_CONTRIBUTION',
            10000,
            is_funder=True
        )
        
        # Both should get REP, funder gets 50% more
        self.assertEqual(creator_rep, 190)  # Logarithmic
        self.assertEqual(funder_rep, 285)   # 190 * 1.5
        self.assertAlmostEqual(funder_rep / creator_rep, 1.5, delta=0.01)


class ConfigurationTests(TestCase):
    """Test configuration overrides."""
    
    @override_settings(CONTRIBUTION_WEIGHT_OVERRIDES={'COMMENT': 5})
    def test_weight_override(self):
        """Content weight overrides should work."""
        rep = ContributionWeight.calculate_reputation_change('COMMENT')
        self.assertEqual(rep, 5)  # Overridden from 0 to 5
    
    @override_settings(VERIFIED_ACCOUNT_BONUS=200)
    def test_verified_bonus_override(self):
        """Verified bonus should be overridable."""
        bonus = ContributionWeight.get_verified_account_bonus()
        self.assertEqual(bonus, 200)
    
    @override_settings(FUNDER_BONUS_MULTIPLIER=2.0)
    def test_funder_multiplier_override(self):
        """Funder multiplier should be overridable."""
        multiplier = ContributionWeight.get_funder_bonus_multiplier()
        self.assertEqual(multiplier, 2.0)


class DocumentationExampleTests(TestCase):
    """Verify examples from docstrings work correctly."""
    
    def test_module_docstring_examples(self):
        """Test all examples from module docstring."""
        # Tip
        self.assertEqual(
            ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', 10),
            10
        )
        
        # Bounty
        self.assertAlmostEqual(
            ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150),
            50,
            delta=2
        )
        
        # Proposal
        self.assertEqual(
            ContributionWeight.calculate_reputation_from_rsc('PROPOSAL_FUNDED', 1000),
            100
        )
        
        # Funder
        self.assertEqual(
            ContributionWeight.calculate_reputation_from_rsc('PROPOSAL_FUNDING_CONTRIBUTION', 1000, is_funder=True),
            150
        )
    
    def test_calculate_reputation_change_examples(self):
        """Test examples from calculate_reputation_change docstring."""
        self.assertEqual(ContributionWeight.calculate_reputation_change('UPVOTE'), 1)
        self.assertEqual(ContributionWeight.calculate_reputation_change('COMMENT'), 0)
        self.assertEqual(ContributionWeight.calculate_reputation_change('PEER_REVIEW'), 0)
        self.assertEqual(ContributionWeight.calculate_reputation_change('BOUNTY_CREATED'), 5)
