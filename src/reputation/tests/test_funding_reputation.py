

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
    
    
    def setUp(self):
        
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
    def test_tip_awards_reputation(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

        self.assertEqual(score_change.rsc_amount, Decimal('10.00'))
        self.assertEqual(score_change.contribution_type, 'TIP_RECEIVED')
        self.assertEqual(score_change.score_change, 10)
        self.assertFalse(score_change.is_deleted)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_bounty_payout_awards_reputation(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('150.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='BOUNTY_PAYOUT',
        )
        

        self.assertEqual(score_change.rsc_amount, Decimal('150.00'))
        self.assertEqual(score_change.contribution_type, 'BOUNTY_PAYOUT')
        self.assertAlmostEqual(score_change.score_change, 50, delta=2)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_proposal_funded_awards_reputation(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('1000.00'),
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            contribution_type='PROPOSAL_FUNDED',
        )
        

        self.assertEqual(score_change.score_change, 100)
        

        score_change2 = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('100000.00'),
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            contribution_type='PROPOSAL_FUNDED',
        )
        

        self.assertEqual(score_change2.score_change, 1090)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_funder_gets_bonus(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('1000.00'),
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
            contribution_type='PROPOSAL_FUNDING_CONTRIBUTION',
            is_funder=True,
        )
        

        self.assertEqual(score_change.score_change, 150)
    
    @override_settings(TIERED_SCORING_ENABLED=False)
    def test_feature_flag_disabled_minimal_scoring(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

        self.assertEqual(score_change.rsc_amount, Decimal('10.00'))
        self.assertEqual(score_change.contribution_type, 'TIP_RECEIVED')
        

        self.assertEqual(score_change.score_change, 0)

class DeletionPenaltyTests(TestCase):
    
    
    def setUp(self):
        
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
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

        score.refresh_from_db()
        self.assertEqual(score.score, 10)
        

        penalty = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        

        self.assertEqual(penalty, 10)
        

        score.refresh_from_db()
        self.assertEqual(score.score, 0)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_keeps_vote_reputation(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

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
                rsc_amount=0,
                is_deleted=False,
            )
            score.score += 1
            score.save()
        

        score.refresh_from_db()
        self.assertEqual(score.score, 15)
        

        penalty = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        

        self.assertEqual(penalty, 10)
        

        score.refresh_from_db()
        self.assertEqual(score.score, 5)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_marks_deleted(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        sc = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        self.assertFalse(sc.is_deleted)
        

        ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        

        sc.refresh_from_db()
        self.assertTrue(sc.is_deleted)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_prevents_double_penalizing(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

        penalty1 = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        self.assertEqual(penalty1, 10)
        

        penalty2 = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        

        self.assertEqual(penalty2, 0)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_creates_penalty_score_change(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

        ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        

        penalty_sc = ScoreChange.objects.filter(
            score=score,
            contribution_type='DELETION_PENALTY'
        ).first()
        
        self.assertIsNotNone(penalty_sc)
        self.assertEqual(penalty_sc.score_change, -10)
        self.assertTrue(penalty_sc.is_deleted)

class UpdateScoreFundingTests(TestCase):
    
    
    def setUp(self):
        
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
        

        score = Score.update_score_funding(
            author=self.author,
            hub=self.hub,
            rsc_amount=Decimal('10.00'),
            content=self.comment,
            contribution_type='TIP_RECEIVED',
        )
        

        self.assertIsNotNone(score)
        self.assertEqual(score.score, 10)
        

        score_changes = ScoreChange.objects.filter(score=score)
        self.assertEqual(score_changes.count(), 1)
        self.assertEqual(score_changes.first().rsc_amount, Decimal('10.00'))
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_update_score_funding_with_funder_bonus(self):
        
        score = Score.update_score_funding(
            author=self.author,
            hub=self.hub,
            rsc_amount=Decimal('1000.00'),
            content=self.paper,
            contribution_type='PROPOSAL_FUNDING_CONTRIBUTION',
            is_funder=True,
        )
        

        self.assertEqual(score.score, 150)

class MultipleRSCFlowsTests(TestCase):
    
    
    def setUp(self):
        
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
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        for amount in [10, 20, 30]:
            ScoreChange.create_score_change_funding(
                score=score,
                rsc_amount=Decimal(str(amount)),
                content_type=ContentType.objects.get_for_model(self.comment),
                object_id=self.comment.id,
                contribution_type='TIP_RECEIVED',
            )
            score.refresh_from_db()
        

        score.refresh_from_db()
        self.assertGreater(score.score, 45)
        self.assertLess(score.score, 55)
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_mixed_rsc_and_votes(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

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
        

        score.refresh_from_db()
        self.assertEqual(score.score, 15)

class VariableCountsTests(TestCase):
    
    
    def setUp(self):
        
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
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        sc1 = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('10.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        
        self.assertEqual(sc1.variable_counts['rsc_received'], 10.0)
        

        sc2 = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('20.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

        self.assertEqual(sc2.variable_counts['rsc_received'], 30.0)

class EdgeCaseTests(TestCase):
    
    
    def setUp(self):
        
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
        
        score = Score.get_or_create_score(self.author, self.hub)
        
        score_change = ScoreChange.create_score_change_funding(
            score=score,
            rsc_amount=Decimal('0.00'),
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
            contribution_type='TIP_RECEIVED',
        )
        

        self.assertEqual(score_change.score_change, 0)
        self.assertEqual(score_change.rsc_amount, Decimal('0.00'))
    
    @override_settings(TIERED_SCORING_ENABLED=True)
    def test_deletion_penalty_on_non_funded_content(self):
        
        score = Score.get_or_create_score(self.author, self.hub)
        

        penalty = ScoreChange.apply_deletion_penalty(
            score=score,
            deleted_content_id=self.comment.id,
            deleted_content_type=ContentType.objects.get_for_model(self.comment),
        )
        

        self.assertEqual(penalty, 0)

