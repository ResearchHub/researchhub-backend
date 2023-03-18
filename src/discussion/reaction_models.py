from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db.models import (
    CASCADE,
    CharField,
    Count,
    DateTimeField,
    ForeignKey,
    IntegerField,
    ManyToManyField,
    PositiveIntegerField,
    Q,
    UniqueConstraint,
)

from discussion.constants.flag_reasons import FLAG_REASON_CHOICES
from utils.models import DefaultModel


class Vote(DefaultModel):
    NEUTRAL = 0
    UPVOTE = 1
    DOWNVOTE = 2
    VOTE_TYPE_CHOICES = [
        (NEUTRAL, "Neutral"),
        (UPVOTE, "Upvote"),
        (DOWNVOTE, "Downvote"),
    ]
    content_type = ForeignKey(ContentType, on_delete=CASCADE)
    object_id = PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")
    distributions = GenericRelation(
        "reputation.Distribution",
        object_id_field="proof_item_object_id",
        content_type_field="proof_item_content_type",
    )
    created_by = ForeignKey(
        "user.User", on_delete=CASCADE, related_name="discussion_votes"
    )
    vote_type = IntegerField(choices=VOTE_TYPE_CHOICES)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["content_type", "object_id", "created_by"], name="unique_vote"
            )
        ]

    def __str__(self):
        return "{} - {}".format(self.created_by, self.vote_type)

    @property
    def paper(self):
        from paper.related_models.paper_model import Paper

        if isinstance(self.item, Paper):
            return self.item

    @property
    def unified_document(self):
        from hypothesis.models import Citation, Hypothesis
        from paper.models import Paper
        from researchhub_comment.models import RhCommentModel
        from researchhub_document.models import ResearchhubPost

        item = self.item
        item_type = type(item)

        if item_type in [Paper, ResearchhubPost, Hypothesis, RhCommentModel]:
            return item.unified_document
        elif item_type is Citation:
            # citation has 1:1 unifiedDoc edge named "source"
            return item.source
        raise Exception("Vote source is missing unified document")


class Flag(DefaultModel):
    verdict_created_date = DateTimeField(null=True)
    content_type = ForeignKey(ContentType, on_delete=CASCADE)
    created_by = ForeignKey("user.User", on_delete=CASCADE)
    item = GenericForeignKey("content_type", "object_id")
    object_id = PositiveIntegerField()
    reason = CharField(max_length=255, blank=True)
    reason_choice = CharField(
        blank=True,
        choices=FLAG_REASON_CHOICES,
        max_length=255,
    )
    hubs = ManyToManyField("hub.Hub", related_name="flags")

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["content_type", "object_id", "created_by"], name="unique_flag"
            )
        ]


class Endorsement(DefaultModel):
    content_type = ForeignKey(ContentType, on_delete=CASCADE)
    created_by = ForeignKey("user.User", on_delete=CASCADE)
    item = GenericForeignKey("content_type", "object_id")
    object_id = PositiveIntegerField()

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["content_type", "object_id"], name="unique_endorsement"
            )
        ]


class AbstractGenericReactionModel(DefaultModel):
    endorsements = GenericRelation(Endorsement)
    flags = GenericRelation(Flag)
    votes = GenericRelation(Vote)

    class Meta:
        abstract = True

    @property
    def score_indexing(self):
        return self.calculate_score()

    @property
    def score(self):
        return self.calculate_score()

    def calculate_score(self):
        qs = self.votes.filter(
            created_by__is_suspended=False, created_by__probable_spammer=False
        )
        score = qs.aggregate(
            score=Count("id", filter=Q(vote_type=Vote.UPVOTE))
            - Count("id", filter=Q(vote_type=Vote.DOWNVOTE))
        ).get("score", 0)
        return score
