from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Count, Q

from discussion.reaction_models import AbstractGenericReactionModel, Vote
from hypothesis.constants.constants import CITATION_TYPE, CITATION_TYPE_CHOICES
from hypothesis.models import Hypothesis
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User


class Citation(AbstractGenericReactionModel):
    created_by = models.ForeignKey(
        User,
        db_index=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_hypothesis_citations",
    )
    hypothesis = models.ManyToManyField(
        Hypothesis, db_index=True, related_name="citations"
    )
    source = models.ForeignKey(
        ResearchhubUnifiedDocument,
        related_name="citation",
        null=False,
        on_delete=models.CASCADE,
    )
    citation_type = models.CharField(
        blank=False,
        choices=CITATION_TYPE_CHOICES,
        db_index=True,
        default=CITATION_TYPE["SUPPORT"],
        help_text="Why citation was added to a hypothesis",
        max_length=255,
    )
    vote_score = models.IntegerField(
        blank=True, db_index=True, default=0, help_text="Updated through signal"
    )
    rh_threads = GenericRelation(
        RhCommentThreadModel,
        help_text="New Comment-Thread module as of Jan 2023",
        related_query_name="citation",
    )

    def __str__(self):
        return f"{self.__class__}"

    def get_promoted_score(self):
        # TODO: leo | thomasvu - add logic / instance method
        return 0

    def calculate_hot_score(self):
        return 0

    def get_vote_score(self):
        vote_set = self.votes.aggregate(
            down_count=Count("id", filter=Q(vote_type=Vote.DOWNVOTE)),
            neutral_count=Count("id", filter=Q(vote_type=Vote.NEUTRAL)),
            up_count=Count("id", filter=Q(vote_type=Vote.UPVOTE)),
        )
        return vote_set["up_count"] - vote_set["down_count"]

    @property
    def unified_document(self):
        return self.source
