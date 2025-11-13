"""
Unit tests for ContributionWeight system.

Tests cover:
- Base weight calculations for all contribution types
- Configuration overrides
- Edge cases and validation
"""

from django.test import TestCase, override_settings

from reputation.related_models.contribution_weight import ContributionWeight


class ContributionWeightBaseTests(TestCase):
    """Test base weight calculations for each contribution type."""
    
    def test_all_base_weights(self):
        """All contribution types should return their correct base weights."""
        test_cases = [
            (ContributionWeight.UPVOTE, 1),
            (ContributionWeight.DOWNVOTE, 1),
            (ContributionWeight.COMMENT, 3),
            (ContributionWeight.THREAD_CREATED, 5),
            (ContributionWeight.BOUNTY_CREATED, 5),
            (ContributionWeight.POST_CREATED, 10),
            (ContributionWeight.PEER_REVIEW, 15),
            (ContributionWeight.BOUNTY_SOLUTION, 20),
            (ContributionWeight.BOUNTY_FUNDED, 30),
            (ContributionWeight.PAPER_PUBLISHED, 50),
        ]
        
        for contribution_type, expected_weight in test_cases:
            with self.subTest(contribution_type=contribution_type):
                rep = ContributionWeight.calculate_reputation_change(
                    contribution_type,
                    {}
                )
                self.assertEqual(rep, expected_weight)


class ContributionWeightContextTests(TestCase):
    """Test that context parameters are ignored"""
    
    def test_context_parameters_ignored(self):
        """Context parameters should not affect reputation"""
        # Upvotes don't affect reputation
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.COMMENT,
            {'upvote_count': 100}
        )
        self.assertEqual(rep, 3)  # Base weight only
        
        # Expert validation doesn't affect reputation
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.PEER_REVIEW,
            {'expert_validated': True}
        )
        self.assertEqual(rep, 15)  # Base weight only
        
        # Bounty amount doesn't affect reputation
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.BOUNTY_SOLUTION,
            {'bounty_amount': 5000}
        )
        self.assertEqual(rep, 20)  # Base weight only
        
        # References don't affect reputation
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.COMMENT,
            {'has_references': True}
        )
        self.assertEqual(rep, 3)  # Base weight only


class ContributionWeightConfigurationTests(TestCase):
    """Test configuration and overrides."""
    
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
    
    @override_settings(CONTRIBUTION_WEIGHT_OVERRIDES={'COMMENT': 5})
    def test_weight_override(self):
        """Configuration should allow weight overrides."""
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.COMMENT,
            {}
        )
        self.assertEqual(rep, 5)  # Overridden from 3 to 5


class ContributionWeightUtilityTests(TestCase):
    """Test utility methods."""
    
    def test_get_contribution_type_display(self):
        """Should return human-readable names."""
        self.assertEqual(
            ContributionWeight.get_contribution_type_display(
                ContributionWeight.UPVOTE
            ),
            'Upvote'
        )
        self.assertEqual(
            ContributionWeight.get_contribution_type_display(
                ContributionWeight.PEER_REVIEW
            ),
            'Peer Review'
        )
    
    def test_get_all_contribution_types(self):
        """Should return list of all contribution types."""
        types = ContributionWeight.get_all_contribution_types()
        
        self.assertIn(ContributionWeight.UPVOTE, types)
        self.assertIn(ContributionWeight.CITATION, types)
        self.assertIn(ContributionWeight.COMMENT, types)
        self.assertIn(ContributionWeight.PEER_REVIEW, types)
        self.assertIn(ContributionWeight.PAPER_PUBLISHED, types)
        self.assertEqual(len(types), 11)
    
    def test_validate_contribution_type_valid(self):
        """Should validate known contribution types."""
        self.assertTrue(
            ContributionWeight.validate_contribution_type(
                ContributionWeight.COMMENT
            )
        )
    
    def test_validate_contribution_type_invalid(self):
        """Should reject unknown contribution types."""
        self.assertFalse(
            ContributionWeight.validate_contribution_type('INVALID_TYPE')
        )


class ContributionWeightEdgeCaseTests(TestCase):
    """Test edge cases and boundary conditions."""
    
    def test_none_context(self):
        """None context should work without errors."""
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.COMMENT,
            None
        )
        self.assertEqual(rep, 3)
    
    def test_empty_context(self):
        """Empty context should return base weight."""
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.COMMENT,
            {}
        )
        self.assertEqual(rep, 3)
    
    def test_zero_upvotes(self):
        """Zero upvotes should return base weight."""
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.COMMENT,
            {'upvote_count': 0}
        )
        self.assertEqual(rep, 3)
    
    def test_negative_upvotes(self):
        """Negative upvotes should return base weight."""
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.COMMENT,
            {'upvote_count': -5}
        )
        self.assertEqual(rep, 3)
    
    def test_zero_bounty_amount(self):
        """Zero bounty should return base weight."""
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.BOUNTY_SOLUTION,
            {'bounty_amount': 0}
        )
        self.assertEqual(rep, 20)
    
    def test_result_never_below_base_weight(self):
        """Final reputation should never be less than base weight."""
        # Even with all zero/false context, should return base weight
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.PEER_REVIEW,
            {
                'expert_validated': False,
                'upvote_count': 0,
                'has_references': False,
            }
        )
        self.assertEqual(rep, 15)
    
    def test_unknown_contribution_type(self):
        """Unknown type should default to weight of 1."""
        rep = ContributionWeight.calculate_reputation_change(
            'UNKNOWN_TYPE',
            {}
        )
        self.assertEqual(rep, 1)
    
    def test_extra_context_keys_ignored(self):
        """Extra context keys should be safely ignored."""
        rep = ContributionWeight.calculate_reputation_change(
            ContributionWeight.COMMENT,
            {
                'upvote_count': 10,
                'extra_key': 'should be ignored',
                'another_key': 12345,
            }
        )
        self.assertEqual(rep, 3)  # Base weight only


class ContributionWeightRegressionTests(TestCase):
    """Regression tests for specific documented scenarios."""
    
    def test_documented_example_simple_upvote(self):
        """Test example from module docstring."""
        rep = ContributionWeight.calculate_reputation_change('UPVOTE', {})
        self.assertEqual(rep, 1)
    
    def test_documented_example_peer_review(self):
        """Test example from module docstring."""
        rep = ContributionWeight.calculate_reputation_change('PEER_REVIEW')
        self.assertEqual(rep, 15)
    
    def test_weight_hierarchy(self):
        """Verify contribution types are properly ordered by effort."""
        # Low effort
        upvote = ContributionWeight.get_base_weight(ContributionWeight.UPVOTE)
        
        # Medium effort
        comment = ContributionWeight.get_base_weight(ContributionWeight.COMMENT)
        thread = ContributionWeight.get_base_weight(ContributionWeight.THREAD_CREATED)
        post = ContributionWeight.get_base_weight(ContributionWeight.POST_CREATED)
        
        # High effort
        review = ContributionWeight.get_base_weight(ContributionWeight.PEER_REVIEW)
        solution = ContributionWeight.get_base_weight(ContributionWeight.BOUNTY_SOLUTION)
        
        # Exceptional effort
        funded = ContributionWeight.get_base_weight(ContributionWeight.BOUNTY_FUNDED)
        paper = ContributionWeight.get_base_weight(ContributionWeight.PAPER_PUBLISHED)
        
        # Verify hierarchy
        self.assertLess(upvote, comment)
        self.assertLess(comment, thread)
        self.assertLess(thread, post)
        self.assertLess(post, review)
        self.assertLess(review, solution)
        self.assertLess(solution, funded)
        self.assertLess(funded, paper)

