"""
Integration tests for funding-based reputation system.

PR #3: Core Integration - Funding-Based Reputation
Tests the create_score_change_funding() and apply_deletion_penalty() methods.
"""

from decimal import Decimal
from django.test import TestCase, override_settings
from django.contrib.contenttypes.models import ContentType

from reputation.models import Score, ScoreChange, AlgorithmVariables
from reputation.related_models.contribution_weight import ContributionWeight
from user.tests.helpers import create_random_authenticated_user
from hub.tests.helpers import create_hub
from researchhub_comment.tests.helpers import create_rh_comment
from paper.tests.helpers import create_paper


class FundingReputationBasicTests(TestCase):
    """Test basic funding reputation functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = create_random_authenticated_user("test_user")
        self.author = self.user.author_profile
        self.hub = create_hub()
        self.paper = create_paper(uploaded_by=self.user)
        self.comment = create_rh_comment(created_by=self.user, paper=self.paper)
        
        # Create algorithm variables
        self.algorithm_variables, _ = AlgorithmVariables.objects.get_or_create(
            hub=self.hub,
            defaults={'variables': {
                'citations': {'bins': {}},
                'votes': {'value': 1}
            }}
        )
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_tip_awards_reputation(self):
        """Tip receipt should award reputation based on amount."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Create score change for $10 tip
        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # $10 tip should award 10 REP (tiered formula)
        self.assertEqual(score_change.rsc_amount, Decimal('10.00'))
        self.assertEqual(score_change.contribution_type, 'TIP_RECEIVED')
        self.assertEqual(score_change.score_change, 10)
        self.assertFalse(score_change.is_deleted)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_bounty_payout_awards_reputation(self):
        """Bounty payout should award generous reputation."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Create score change for $150 bounty (standard peer review)
        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('150.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='BOUNTY_PAYOUT',
        )
        
        # $150 bounty should award ~50 REP
        self.assertEqual(score_change.rsc_amount, Decimal('150.00'))
        self.assertEqual(score_change.contribution_type, 'BOUNTY_PAYOUT')
        self.assertAlmostEqual(score_change.score_change, 50, delta=2)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_proposal_funded_awards_reputation(self):
        """Proposal funding should use logarithmic scaling."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Small proposal
        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('1000.00'),
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            contribution_type='PROPOSAL_FUNDED',
        )
        
        # $1000 → 100 REP (tier 1)
        self.assertEqual(score_change.score_change, 100)
        
        # Large proposal
        score_change2 = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('100000.00'),
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            contribution_type='PROPOSAL_FUNDED',
        )
        
        # $100K → 1,090 REP (logarithmic)
        self.assertEqual(score_change2.score_change, 1090)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_funder_gets_bonus(self):
        """Funders should get 1.5x bonus on proposal funding."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Fund $1000 proposal as funder
        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('1000.00'),
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            contribution_type='PROPOSAL_FUNDING_CONTRIBUTION',
            is_funder=True,
        )
        
        # $1000 → 100 REP × 1.5 = 150 REP
        self.assertEqual(score_change.score_change, 150)
    
    @override_settings(TIERED_SCORING_ENABLED=False)
    def test_feature_flag_disabled_minimal_scoring(self):
        """When feature flag is OFF, should give minimal REP but still track data."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Create score change with flag OFF
        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # Should still track data
        self.assertEqual(score_change.rsc_amount, Decimal('10.00'))
        self.assertEqual(score_change.contribution_type, 'TIP_RECEIVED')
        
        # But score change should be minimal (0 in this implementation)
        self.assertEqual(score_change.score_change, 0)


class DeletionPenaltyTests(TestCase):
    """Test content deletion penalty logic."""
    
    def setUp(self):
        """Set up test data."""
        self.user = create_random_authenticated_user("test_user")
        self.author = self.user.author_profile
        self.hub = create_hub()
        self.paper = create_paper(uploaded_by=self.user)
        self.comment = create_rh_comment(created_by=self.user, paper=self.paper)
        
        self.algorithm_variables, _ = AlgorithmVariables.objects.get_or_create(
            hub=self.hub,
            defaults={'variables': {
                'citations': {'bins': {}},
                'votes': {'value': 1}
            }}
        )
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_deducts_rsc_reputation(self):
        """Deleting funded content should deduct RSC-based reputation."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Receive $10 tip
        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # Score should be 10
        score.refresh_from_db()
        self.assertEqual(score.score, 10)
        
        # Apply deletion penalty
        penalty = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        
        # Penalty should be 10 REP
        self.assertEqual(penalty, 10)
        
        # Score should now be 0
        score.refresh_from_db()
        self.assertEqual(score.score, 0)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_keeps_vote_reputation(self):
        """Deleting content should keep vote-based reputation (voters earned those)."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Receive $10 tip
        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # Receive 5 upvotes (vote-based, rsc_amount=0)
        for i in range(5):
            ScoreChange.objects.create(
                score=score,
                algorithm_version=2,
                algorithm_variables=self.algorithm_variables,
                score_after_change=score.score + 1,
                score_change=1,
                raw_value_change=1,
                changed_content_type=ContentType.objects.get_for_model(self.comment),
                changed_object_id=self.comment.id,
                changed_object_field="vote_type",
                variable_counts={"citations": 0, "votes": i+1, "rsc_received": 10},
                contribution_type='UPVOTE',
                rsc_amount=0,  # Vote-based, no RSC
                is_deleted=False,
            )
            score.score += 1
            score.save()
        
        # Score should be 15 (10 from tip + 5 from upvotes)
        score.refresh_from_db()
        self.assertEqual(score.score, 15)
        
        # Apply deletion penalty
        penalty = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        
        # Penalty should only be 10 (tip), not 15 (tip + votes)
        self.assertEqual(penalty, 10)
        
        # Score should be 5 (kept vote reputation)
        score.refresh_from_db()
        self.assertEqual(score.score, 5)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_marks_deleted(self):
        """Deletion penalty should mark score changes as deleted."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Receive tip
        sc = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        self.assertFalse(sc.is_deleted)
        
        # Apply deletion penalty
        ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        
        # Score change should now be marked as deleted
        sc.refresh_from_db()
        self.assertTrue(sc.is_deleted)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_prevents_double_penalizing(self):
        """Applying penalty twice should not double-deduct."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Receive tip
        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # Apply penalty once
        penalty1 = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        self.assertEqual(penalty1, 10)
        
        # Try to apply again
        penalty2 = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        
        # Should not apply penalty again (already marked deleted)
        self.assertEqual(penalty2, 0)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_creates_penalty_score_change(self):
        """Deletion should create a DELETION_PENALTY score change record."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Receive tip
        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # Apply deletion penalty
        ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        
        # Should have created a DELETION_PENALTY score change
        penalty_sc = ScoreChange.objects.filter(
            score=score,
            contribution_type='DELETION_PENALTY'
        ).first()
        
        self.assertIsNotNone(penalty_sc)
        self.assertEqual(penalty_sc.score_change, -10)
        self.assertTrue(penalty_sc.is_deleted)


class UpdateScoreFundingTests(TestCase):
    """Test the Score.update_score_funding() wrapper method."""
    
    def setUp(self):
        """Set up test data."""
        self.user = create_random_authenticated_user("test_user")
        self.author = self.user.author_profile
        self.hub = create_hub()
        self.paper = create_paper(uploaded_by=self.user)
        self.comment = create_rh_comment(created_by=self.user, paper=self.paper)
        
        AlgorithmVariables.objects.get_or_create(
            hub=self.hub,
            defaults={'variables': {
                'citations': {'bins': {}},
                'votes': {'value': 1}
            }}
        )
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_update_score_funding_wrapper(self):
        """update_score_funding should be a convenient wrapper."""
        # Use wrapper method
        score = Score.update_score_funding(
            author=self.author,
            hub=self.hub,
            rsc_amount=Decimal('10.00'),
            content=self.comment,
            contribution_type='TIP_RECEIVED',
        )
        
        # Should create score and score change
        self.assertIsNotNone(score)
        self.assertEqual(score.score, 10)
        
        # Should have created score change
        score_changes = ScoreChange.objects.filter(score=score)
        self.assertEqual(score_changes.count(), 1)
        self.assertEqual(score_changes.first().rsc_amount, Decimal('10.00'))
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_update_score_funding_with_funder_bonus(self):
        """update_score_funding should support funder bonus."""
        score = Score.update_score_funding(
            author=self.author,
            hub=self.hub,
            rsc_amount=Decimal('1000.00'),
            content=self.paper,
            contribution_type='PROPOSAL_FUNDING_CONTRIBUTION',
            is_funder=True,
        )
        
        # $1000 with funder bonus should be 150 REP
        self.assertEqual(score.score, 150)


class MultipleRSCFlowsTests(TestCase):
    """Test scenarios with multiple RSC flows."""
    
    def setUp(self):
        """Set up test data."""
        self.user = create_random_authenticated_user("test_user")
        self.author = self.user.author_profile
        self.hub = create_hub()
        self.paper = create_paper(uploaded_by=self.user)
        self.comment = create_rh_comment(created_by=self.user, paper=self.paper)
        
        AlgorithmVariables.objects.get_or_create(
            hub=self.hub,
            defaults={'variables': {
                'citations': {'bins': {}},
                'votes': {'value': 1}
            }}
        )
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_multiple_tips_accumulate(self):
        """Multiple tips should accumulate reputation."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Receive 3 tips
        for amount in [10, 20, 30]:
            ScoreChange.create_score_change_funding(
                score=score,
                rsc_amount=Decimal(str(amount)),
                content_type=ContentType.objects.get_for_model(self.comment),
                object_id=self.comment.id,
                contribution_type='TIP_RECEIVED',
            )
            score.refresh_from_db()
        
        # Total should be sum of individual REP calculations
        # $10 → 10, $20 → 17, $30 → 24 = ~51 total
        score.refresh_from_db()
        self.assertGreater(score.score, 45)
        self.assertLess(score.score, 55)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_mixed_rsc_and_votes(self):
        """RSC-based and vote-based reputation should work together."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Receive tip
        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # Receive upvotes
        for i in range(5):
            ScoreChange.objects.create(
                score=score,
                algorithm_version=2,
                algorithm_variables=AlgorithmVariables.objects.filter(hub=self.hub).latest("created_date"),
                score_after_change=score.score + 1,
                score_change=1,
                raw_value_change=1,
                changed_content_type=ContentType.objects.get_for_model(self.comment),
                changed_object_id=self.comment.id,
                changed_object_field="vote_type",
                variable_counts={"citations": 0, "votes": i+1, "rsc_received": 10},
                contribution_type='UPVOTE',
                rsc_amount=0,
                is_deleted=False,
            )
            score.score += 1
            score.save()
        
        # Total: 10 (tip) + 5 (votes) = 15
        score.refresh_from_db()
        self.assertEqual(score.score, 15)


class VariableCountsTests(TestCase):
    """Test that rsc_received is tracked in variable_counts."""
    
    def setUp(self):
        """Set up test data."""
        self.user = create_random_authenticated_user("test_user")
        self.author = self.user.author_profile
        self.hub = create_hub()
        self.comment = create_rh_comment(created_by=self.user)
        
        AlgorithmVariables.objects.get_or_create(
            hub=self.hub,
            defaults={'variables': {
                'citations': {'bins': {}},
                'votes': {'value': 1}
            }}
        )
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_rsc_received_tracked_in_variable_counts(self):
        """RSC amounts should be tracked in variable_counts."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Receive $10 tip
        sc1 = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        self.assertEqual(sc1.variable_counts['rsc_received'], 10.0)
        
        # Receive $20 more
        sc2 = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('20.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # Should accumulate
        self.assertEqual(sc2.variable_counts['rsc_received'], 30.0)


class EdgeCaseTests(TestCase):
    """Test edge cases."""
    
    def setUp(self):
        """Set up test data."""
        self.user = create_random_authenticated_user("test_user")
        self.author = self.user.author_profile
        self.hub = create_hub()
        self.comment = create_rh_comment(created_by=self.user)
        
        AlgorithmVariables.objects.get_or_create(
            hub=self.hub,
            defaults={'variables': {
                'citations': {'bins': {}},
                'votes': {'value': 1}
            }}
        )
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_zero_rsc_amount(self):
        """Zero RSC amount should be handled gracefully."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('0.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        # Should create record but give 0 REP
        self.assertEqual(score_change.score_change, 0)
        self.assertEqual(score_change.rsc_amount, Decimal('0.00'))
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_on_non_funded_content(self):
        """Applying penalty on non-funded content should do nothing."""
        score = Score.get_or_create_score(self.author, self.hub)
        
        # Apply penalty on content with no RSC
        penalty = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        
        # Should be 0 (no RSC-based score changes to penalize)
        self.assertEqual(penalty, 0)

