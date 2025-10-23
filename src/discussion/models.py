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
    TextField,
    UniqueConstraint,
)

from discussion.constants.flag_reasons import FLAG_REASON_CHOICES
from purchase.models import Purchase
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
        from paper.models import Paper
        from researchhub_comment.models import RhCommentModel
        from researchhub_document.models import ResearchhubPost

        item = self.item
        item_type = type(item)

        if item_type in [
            Paper,
            ResearchhubPost,
            RhCommentModel,
        ]:
            return item.unified_document

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
    reason_memo = TextField(blank=True, default="")
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


class Interest(DefaultModel):
    DISMISSED = 1
    INTEREST_TYPE_CHOICES = [
        (DISMISSED, "Dismissed"),
    ]
    content_type = ForeignKey(ContentType, on_delete=CASCADE)
    created_by = ForeignKey("user.User", on_delete=CASCADE, related_name="interests")
    item = GenericForeignKey("content_type", "object_id")
    object_id = PositiveIntegerField()
    interest_type = IntegerField(choices=INTEREST_TYPE_CHOICES, default=DISMISSED)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["content_type", "object_id", "created_by"],
                name="unique_interest",
            )
        ]

    def __str__(self):
        return f"{self.created_by} - {self.get_interest_type_display()}"


class AbstractGenericReactionModel(DefaultModel):
    endorsements = GenericRelation(Endorsement)
    flags = GenericRelation(Flag)
    votes = GenericRelation(Vote)
    interests = GenericRelation(Interest)
    score = IntegerField(default=0)

    class Meta:
        abstract = True

    def calculate_score(self):
        qs = self.votes.filter(
            created_by__is_suspended=False, created_by__probable_spammer=False
        )
        score = qs.aggregate(
            score=Count("id", filter=Q(vote_type=Vote.UPVOTE))
            - Count("id", filter=Q(vote_type=Vote.DOWNVOTE))
        ).get("score", 0)
        return score

    def get_promoted_score(self):
        purchases = self.purchases.filter(
            paid_status=Purchase.PAID,
        )
        if purchases.exists():
            boost_score = sum(map(int, purchases.values_list("amount", flat=True)))
            return boost_score
        return False
