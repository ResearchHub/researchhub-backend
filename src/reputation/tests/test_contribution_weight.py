from django.test import TestCase, override_settings

from reputation.related_models.contribution_weight import ContributionWeight


class TipReputationTests(TestCase):
    
    def test_tip_curved_scaling(self):
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
                self.assertAlmostEqual(rep, expected_rep, delta=1)
    
    def test_tip_zero_amount(self):
        rep = ContributionWeight.calculate_tip_reputation(0)
        self.assertEqual(rep, 0)
    
    def test_tip_negative_amount(self):
        rep = ContributionWeight.calculate_tip_reputation(-10)
        self.assertEqual(rep, 0)
    
    def test_tip_via_main_method(self):
        rep = ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', 10)
        self.assertEqual(rep, 10)


class BountyReputationTests(TestCase):
    
    def test_bounty_tier_1(self):
        rep = ContributionWeight.calculate_bounty_reputation(150)
        self.assertEqual(rep, 49)
    
    def test_bounty_tier_2(self):
        rep = ContributionWeight.calculate_bounty_reputation(500)
        self.assertAlmostEqual(rep, 140, delta=2)
    
    def test_bounty_tier_3(self):
        rep = ContributionWeight.calculate_bounty_reputation(2000)
        self.assertAlmostEqual(rep, 540, delta=5)
    
    def test_bounty_zero_amount(self):
        rep = ContributionWeight.calculate_bounty_reputation(0)
        self.assertEqual(rep, 0)
    
    def test_bounty_via_main_method(self):
        rep = ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
        self.assertAlmostEqual(rep, 50, delta=2)


class ProposalReputationTests(TestCase):
    
    def test_proposal_tier_1(self):
        rep = ContributionWeight.calculate_proposal_reputation(1000, is_funder=False)
        self.assertEqual(rep, 100)
    
    def test_proposal_tier_2(self):
        rep = ContributionWeight.calculate_proposal_reputation(10000, is_funder=False)
        self.assertEqual(rep, 190)
    
    def test_proposal_tier_3(self):
        rep = ContributionWeight.calculate_proposal_reputation(100000, is_funder=False)
        self.assertEqual(rep, 1090)
    
    def test_proposal_mega(self):
        rep = ContributionWeight.calculate_proposal_reputation(1000000, is_funder=False)
        self.assertEqual(rep, 1990)
    
    def test_proposal_funder_bonus(self):
        rep_receiver = ContributionWeight.calculate_proposal_reputation(1000, is_funder=False)
        rep_funder = ContributionWeight.calculate_proposal_reputation(1000, is_funder=True)
        
        self.assertEqual(rep_receiver, 100)
        self.assertEqual(rep_funder, 150)
    
    def test_proposal_tier_4_mega(self):
        rep = ContributionWeight.calculate_proposal_reputation(2000000, is_funder=False)
        self.assertEqual(rep, 2090)
    
    def test_proposal_tier_4_with_funder_bonus(self):
        rep = ContributionWeight.calculate_proposal_reputation(2000000, is_funder=True)
        self.assertEqual(rep, 3135)
    
    def test_proposal_zero_amount(self):
        rep = ContributionWeight.calculate_proposal_reputation(0, is_funder=False)
        self.assertEqual(rep, 0)
    
    def test_proposal_negative_amount(self):
        rep = ContributionWeight.calculate_proposal_reputation(-1000, is_funder=False)
        self.assertEqual(rep, 0)
    
    def test_proposal_funder_bonus_large_amount(self):
        rep_receiver = ContributionWeight.calculate_proposal_reputation(100000, is_funder=False)
        rep_funder = ContributionWeight.calculate_proposal_reputation(100000, is_funder=True)
        
        self.assertEqual(rep_receiver, 1090)
        self.assertEqual(rep_funder, 1635)
    
    def test_proposal_via_main_method(self):
        rep = ContributionWeight.calculate_reputation_from_rsc('PROPOSAL_FUNDED', 1000)
        self.assertEqual(rep, 100)


class ContentCreationTests(TestCase):
    
    def test_comment_zero_rep(self):
        rep = ContributionWeight.calculate_reputation_change('COMMENT')
        self.assertEqual(rep, 0)
    
    def test_peer_review_zero_rep(self):
        rep = ContributionWeight.calculate_reputation_change('PEER_REVIEW')
        self.assertEqual(rep, 0)
    
    def test_thread_minimal_rep(self):
        rep = ContributionWeight.calculate_reputation_change('THREAD_CREATED')
        self.assertEqual(rep, 1)
    
    def test_post_minimal_rep(self):
        rep = ContributionWeight.calculate_reputation_change('POST_CREATED')
        self.assertEqual(rep, 2)
    
    def test_bounty_created_keeps_rep(self):
        rep = ContributionWeight.calculate_reputation_change('BOUNTY_CREATED')
        self.assertEqual(rep, 5)


class EngagementTests(TestCase):
    
    def test_upvote_gives_one_rep(self):
        rep = ContributionWeight.calculate_reputation_change('UPVOTE')
        self.assertEqual(rep, 1)
    
    def test_downvote_negative_rep(self):
        rep = ContributionWeight.calculate_reputation_change('DOWNVOTE')
        self.assertEqual(rep, -1)


class VerifiedAccountTests(TestCase):
    
    def test_verified_account_bonus_default(self):
        bonus = ContributionWeight.get_verified_account_bonus()
        self.assertEqual(bonus, 100)
    
    @override_settings(VERIFIED_ACCOUNT_BONUS=200)
    def test_verified_account_bonus_override(self):
        bonus = ContributionWeight.get_verified_account_bonus()
        self.assertEqual(bonus, 200)


class FunderBonusTests(TestCase):
    
    def test_funder_bonus_default(self):
        multiplier = ContributionWeight.get_funder_bonus_multiplier()
        self.assertEqual(multiplier, 1.5)
    
    @override_settings(FUNDER_BONUS_MULTIPLIER=2.0)
    def test_funder_bonus_override(self):
        multiplier = ContributionWeight.get_funder_bonus_multiplier()
        self.assertEqual(multiplier, 2.0)


class FeatureFlagTests(TestCase):
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_feature_flag_enabled(self):
        self.assertTrue(ContributionWeight.is_tiered_scoring_enabled())
    
    @override_settings(TIERED_SCORING_ENABLED=False)
    def test_feature_flag_disabled(self):
        self.assertFalse(ContributionWeight.is_tiered_scoring_enabled())
    
    def test_feature_flag_default(self):
        self.assertFalse(ContributionWeight.is_tiered_scoring_enabled())


class UtilityMethodTests(TestCase):
    
    def test_get_contribution_type_display(self):
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
        types = ContributionWeight.get_all_contribution_types()
        
        self.assertIn('UPVOTE', types)
        self.assertIn('TIP_RECEIVED', types)
        self.assertIn('BOUNTY_PAYOUT', types)
        self.assertIn('PROPOSAL_FUNDED', types)
        self.assertIn('COMMENT', types)
    
    def test_validate_contribution_type_valid(self):
        self.assertTrue(ContributionWeight.validate_contribution_type('UPVOTE'))
        self.assertTrue(ContributionWeight.validate_contribution_type('TIP_RECEIVED'))
    
    def test_validate_contribution_type_invalid(self):
        self.assertFalse(ContributionWeight.validate_contribution_type('INVALID_TYPE'))


class EdgeCaseTests(TestCase):
    
    def test_rsc_amount_zero(self):
        rep = ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', 0)
        self.assertEqual(rep, 0)
    
    def test_rsc_amount_negative(self):
        rep = ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', -10)
        self.assertEqual(rep, 0)
    
    def test_unknown_rsc_type(self):
        rep = ContributionWeight.calculate_reputation_from_rsc('UNKNOWN_TYPE', 100)
        self.assertEqual(rep, 0)
    
    def test_unknown_contribution_type(self):
        rep = ContributionWeight.calculate_reputation_change('UNKNOWN_TYPE')
        self.assertEqual(rep, 0)


class RegressionTests(TestCase):
    
    def test_quality_peer_reviewer_scenario(self):
        bounty_rep = sum(
            ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
            for _ in range(10)
        )
        
        self.assertAlmostEqual(bounty_rep, 500, delta=10)
    
    def test_generous_funder_scenario(self):
        funding_rep = ContributionWeight.calculate_reputation_from_rsc(
            'PROPOSAL_FUNDING_CONTRIBUTION',
            5000,
            is_funder=True
        )
        
        self.assertAlmostEqual(funding_rep, 210, delta=10)
    
    def test_verified_vs_quality_work(self):
        verified_rep = ContributionWeight.VERIFIED_ACCOUNT_BONUS
        
        quality_rep = sum(
            ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
            for _ in range(3)
        )
        
        self.assertGreater(quality_rep, verified_rep)
        self.assertGreater(quality_rep / verified_rep, 1.3)


class IntegrationTests(TestCase):
    
    def test_complete_user_journey(self):
        total_rep = 0
        total_rep += ContributionWeight.VERIFIED_ACCOUNT_BONUS
        
        for _ in range(3):
            total_rep += ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150)
        
        total_rep += ContributionWeight.calculate_tip_reputation(120)
        total_rep += 50 * ContributionWeight.calculate_reputation_change('UPVOTE')
        total_rep += 2 * ContributionWeight.calculate_reputation_change('BOUNTY_CREATED')
        total_rep += ContributionWeight.calculate_reputation_from_rsc(
            'PROPOSAL_FUNDING_CONTRIBUTION', 
            500, 
            is_funder=True
        )
        
        self.assertGreater(total_rep, 400)
        self.assertLess(total_rep, 500)
    
    def test_proposal_funding_both_sides(self):
        creator_rep = ContributionWeight.calculate_reputation_from_rsc(
            'PROPOSAL_FUNDED',
            10000,
            is_funder=False
        )
        
        funder_rep = ContributionWeight.calculate_reputation_from_rsc(
            'PROPOSAL_FUNDING_CONTRIBUTION',
            10000,
            is_funder=True
        )
        
        self.assertEqual(creator_rep, 190)
        self.assertEqual(funder_rep, 285)
        self.assertAlmostEqual(funder_rep / creator_rep, 1.5, delta=0.01)


class ConfigurationTests(TestCase):
    
    @override_settings(CONTRIBUTION_WEIGHT_OVERRIDES={'COMMENT': 5})
    def test_weight_override(self):
        rep = ContributionWeight.calculate_reputation_change('COMMENT')
        self.assertEqual(rep, 5)
    
    @override_settings(VERIFIED_ACCOUNT_BONUS=200)
    def test_verified_bonus_override(self):
        bonus = ContributionWeight.get_verified_account_bonus()
        self.assertEqual(bonus, 200)
    
    @override_settings(FUNDER_BONUS_MULTIPLIER=2.0)
    def test_funder_multiplier_override(self):
        multiplier = ContributionWeight.get_funder_bonus_multiplier()
        self.assertEqual(multiplier, 2.0)


class DocumentationExampleTests(TestCase):
    
    def test_module_docstring_examples(self):
        self.assertEqual(
            ContributionWeight.calculate_reputation_from_rsc('TIP_RECEIVED', 10),
            10
        )
        
        self.assertAlmostEqual(
            ContributionWeight.calculate_reputation_from_rsc('BOUNTY_PAYOUT', 150),
            50,
            delta=2
        )
        
        self.assertEqual(
            ContributionWeight.calculate_reputation_from_rsc('PROPOSAL_FUNDED', 1000),
            100
        )
        
        self.assertEqual(
            ContributionWeight.calculate_reputation_from_rsc('PROPOSAL_FUNDING_CONTRIBUTION', 1000, is_funder=True),
            150
        )
    
    def test_calculate_reputation_change_examples(self):
        self.assertEqual(ContributionWeight.calculate_reputation_change('UPVOTE'), 1)
        self.assertEqual(ContributionWeight.calculate_reputation_change('COMMENT'), 0)
        self.assertEqual(ContributionWeight.calculate_reputation_change('PEER_REVIEW'), 0)
        self.assertEqual(ContributionWeight.calculate_reputation_change('BOUNTY_CREATED'), 5)
