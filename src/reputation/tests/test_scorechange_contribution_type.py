"""
Tests for ScoreChange contribution_type field.

Verifies that the contribution_type field is properly stored and retrieved.
"""

from django.test import TestCase
from django.contrib.contenttypes.models import ContentType

from reputation.models import Score, ScoreChange, AlgorithmVariables
from reputation.related_models.contribution_weight import ContributionWeight
from user.tests.helpers import create_random_authenticated_user
from hub.tests.helpers import create_hub


class ScoreChangeContributionTypeTests(TestCase):
    """Test contribution_type field on ScoreChange model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = create_random_authenticated_user("test_user")
        self.author = self.user.author_profile
        self.hub = create_hub()
        
        self.algorithm_variables = AlgorithmVariables.objects.create(
            hub=self.hub,
            variables={
                "vote": {"value": 1},
                "citations": {"bins": {}},
            },
        )
        
        self.score = Score.get_or_create_score(self.author, self.hub)
    
    def test_scorechange_has_contribution_type_field(self):
        """ScoreChange should have contribution_type field."""
        score_change = ScoreChange.objects.create(
            algorithm_version=2,
            algorithm_variables=self.algorithm_variables,
            score_after_change=10,
            score_change=10,
            raw_value_change=1,
            changed_content_type=ContentType.objects.get_for_model(Score),
            changed_object_id=self.score.id,
            changed_object_field='score',
            variable_counts={},
            score=self.score,
            contribution_type=ContributionWeight.COMMENT,
        )
        
        self.assertEqual(score_change.contribution_type, ContributionWeight.COMMENT)
        
        retrieved = ScoreChange.objects.get(id=score_change.id)
        self.assertEqual(retrieved.contribution_type, ContributionWeight.COMMENT)
    
    def test_scorechange_contribution_type_default(self):
        """ScoreChange should default to UPVOTE if not specified."""
        score_change = ScoreChange.objects.create(
            algorithm_version=2,
            algorithm_variables=self.algorithm_variables,
            score_after_change=5,
            score_change=5,
            raw_value_change=1,
            changed_content_type=ContentType.objects.get_for_model(Score),
            changed_object_id=self.score.id,
            changed_object_field='score',
            variable_counts={},
            score=self.score,
        )
        
        self.assertEqual(score_change.contribution_type, 'UPVOTE')
    
    def test_scorechange_query_by_contribution_type(self):
        """Should be able to query ScoreChange by contribution_type."""
        ScoreChange.objects.create(
            algorithm_version=2,
            algorithm_variables=self.algorithm_variables,
            score_after_change=3,
            score_change=3,
            raw_value_change=1,
            changed_content_type=ContentType.objects.get_for_model(Score),
            changed_object_id=self.score.id,
            changed_object_field='score',
            variable_counts={},
            score=self.score,
            contribution_type=ContributionWeight.COMMENT,
        )
        
        ScoreChange.objects.create(
            algorithm_version=2,
            algorithm_variables=self.algorithm_variables,
            score_after_change=18,
            score_change=15,
            raw_value_change=1,
            changed_content_type=ContentType.objects.get_for_model(Score),
            changed_object_id=self.score.id,
            changed_object_field='score',
            variable_counts={},
            score=self.score,
            contribution_type=ContributionWeight.PEER_REVIEW,
        )
        
        ScoreChange.objects.create(
            algorithm_version=2,
            algorithm_variables=self.algorithm_variables,
            score_after_change=19,
            score_change=1,
            raw_value_change=1,
            changed_content_type=ContentType.objects.get_for_model(Score),
            changed_object_id=self.score.id,
            changed_object_field='score',
            variable_counts={},
            score=self.score,
            contribution_type=ContributionWeight.UPVOTE,
        )
        
        comments = ScoreChange.objects.filter(
            contribution_type=ContributionWeight.COMMENT
        )
        self.assertEqual(comments.count(), 1)
        self.assertEqual(comments.first().score_change, 3)
        
        reviews = ScoreChange.objects.filter(
            contribution_type=ContributionWeight.PEER_REVIEW
        )
        self.assertEqual(reviews.count(), 1)
        self.assertEqual(reviews.first().score_change, 15)
        
        upvotes = ScoreChange.objects.filter(
            contribution_type=ContributionWeight.UPVOTE
        )
        self.assertEqual(upvotes.count(), 1)
        self.assertEqual(upvotes.first().score_change, 1)
    
    def test_scorechange_index_on_contribution_type(self):
        """Verify indexes exist for efficient querying."""
        indexes = ScoreChange._meta.indexes
        index_names = [idx.name for idx in indexes]
        
        self.assertIn('idx_score_contribution_type', index_names)
        self.assertIn('idx_contribution_type_date', index_names)
    
    def test_all_contribution_types_can_be_stored(self):
        """All ContributionWeight types should be storable."""
        contribution_types = [
            ContributionWeight.UPVOTE,
            ContributionWeight.DOWNVOTE,
            ContributionWeight.CITATION,
            ContributionWeight.COMMENT,
            ContributionWeight.THREAD_CREATED,
            ContributionWeight.BOUNTY_CREATED,
            ContributionWeight.POST_CREATED,
            ContributionWeight.PEER_REVIEW,
            ContributionWeight.BOUNTY_SOLUTION,
            ContributionWeight.BOUNTY_FUNDED,
            ContributionWeight.PAPER_PUBLISHED,
        ]
        
        created_changes = []
        for contrib_type in contribution_types:
            score_change = ScoreChange.objects.create(
                algorithm_version=2,
                algorithm_variables=self.algorithm_variables,
                score_after_change=10,
                score_change=10,
                raw_value_change=1,
                changed_content_type=ContentType.objects.get_for_model(Score),
                changed_object_id=self.score.id,
                changed_object_field='score',
                variable_counts={},
                score=self.score,
                contribution_type=contrib_type,
            )
            created_changes.append(score_change)
        
        self.assertEqual(len(created_changes), len(contribution_types))
        
        for idx, score_change in enumerate(created_changes):
            retrieved = ScoreChange.objects.get(id=score_change.id)
            self.assertEqual(retrieved.contribution_type, contribution_types[idx])

