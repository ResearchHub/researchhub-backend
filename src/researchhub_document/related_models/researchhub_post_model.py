import logging

from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Exists, IntegerField, OuterRef, Q, Sum
from django.db.models.functions import Cast
from django.utils.functional import cached_property

from discussion.models import AbstractGenericReactionModel, Vote
from purchase.models import Grant, Purchase
from researchhub_access_group.constants import NO_ACCESS
from researchhub_access_group.models import Permission
from researchhub_comment.models import RhCommentThreadModel
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    DOCUMENT_TYPES,
    REGISTERED_REPORT,
    RESEARCHHUB_POST_DOCUMENT_TYPES,
)
from researchhub_document.related_models.constants.editor_type import (
    CK_EDITOR,
    EDITOR_TYPES,
)
from researchhub_document.related_models.constants.journey_stage import (
    JOURNEY_STAGE_BY_DOCUMENT_TYPE,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import Author, User

logger = logging.getLogger(__name__)


class ResearchhubPostQuerySet(models.QuerySet):
    def publicly_visible(self) -> "ResearchhubPostQuerySet":
        """Restrict to posts safe for anonymous/public discovery surfaces."""
        return self.filter(self._public_visibility_filter())

    def visible_to(self, user: User | None) -> "ResearchhubPostQuerySet":
        """Restrict to posts the given user is allowed to see.

        Anonymous users only see public posts that cleared moderation. Authors
        can see their own posts. Grant creators and document-permission users
        can see private posts after moderation clears; ``NO_ACCESS`` still wins.
        Moderators and hub editors can see all posts.

        Grant posts do not use unified-document moderation status. Their backing
        document stays approved, so ``Grant.status`` decides whether they cleared.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return self.publicly_visible()

        if user.is_moderator_or_editor():
            return self

        moderation_approved = self._moderation_approved_filter()
        ud_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        user_perms = Permission.objects.filter(
            content_type=ud_ct,
            object_id=OuterRef("unified_document_id"),
            user=user,
        )
        allowed = user_perms.exclude(access_type=NO_ACCESS)
        revoked = user_perms.filter(access_type=NO_ACCESS)

        created_by_user = Q(created_by=user)

        visible_to_grant_or_permitted = moderation_approved & (
            Q(grant_applications__grant__created_by=user)
            | (Exists(allowed) & ~Exists(revoked))
        )

        return self.filter(
            self._public_visibility_filter()
            | created_by_user
            | visible_to_grant_or_permitted
        ).distinct()

    def _public_visibility_filter(self) -> Q:
        return Q(unified_document__is_public=True) & self._moderation_approved_filter()

    @staticmethod
    def _moderation_approved_filter() -> Q:
        pending_grant = Grant.objects.filter(
            unified_document_id=OuterRef("unified_document_id"),
            status__in=Grant.PENDING_MODERATION_STATUSES,
        )
        return Q(
            unified_document__status=ResearchhubUnifiedDocument.APPROVED
        ) & ~Exists(pending_grant)


class ResearchhubPost(AbstractGenericReactionModel):
    authors = models.ManyToManyField(
        Author,
        related_name="authored_posts",
    )
    created_by = models.ForeignKey(
        User,
        db_index=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_posts",
    )
    discussion_count = models.IntegerField(default=0, db_index=True)
    discussion_src = models.FileField(
        blank=True,
        default=None,
        max_length=512,
        null=True,
        upload_to="uploads/post_discussion/%Y/%m/%d/",
    )
    document_type = models.CharField(
        choices=DOCUMENT_TYPES,
        default=DISCUSSION,
        max_length=32,
        null=False,
    )
    editor_type = models.CharField(
        choices=EDITOR_TYPES,
        default=CK_EDITOR,
        max_length=32,
        help_text="Editor used to compose the post",
    )
    eln_src = models.FileField(
        blank=True,
        default=None,
        max_length=512,
        null=True,
        upload_to="uploads/post_eln/%Y/%m/%d/",
    )
    image = models.TextField(
        blank=True,
        null=True,
        default=None,
    )
    journey = models.ForeignKey(
        "researchhub_document.ResearchJourney",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="stage_posts",
    )
    note = models.OneToOneField(
        "note.Note",
        null=True,
        related_name="post",
        on_delete=models.CASCADE,
    )
    prev_version = models.OneToOneField(
        "self",
        blank=True,
        default=None,
        null=True,
        on_delete=models.SET_NULL,
        related_name="next_version",
    )
    preview_img = models.URLField(
        blank=True,
        default=None,
        null=True,
    )
    renderable_text = models.TextField(
        blank=True,
        default="",
    )
    rh_threads = GenericRelation(
        RhCommentThreadModel,
        help_text="New Comment-Thread module as of Jan 2023",
        related_query_name="rh_post",
    )
    bounty_type = models.CharField(blank=True, null=True, max_length=64)
    title = models.TextField(blank=True, default="")
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        db_index=True,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    version_number = models.IntegerField(
        blank=False,
        default=1,
        null=False,
    )
    purchases = GenericRelation(
        "purchase.Purchase",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="post",
    )
    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="posts",
    )
    # This is already inherited from the base class
    # but is required to set the related lookup name
    votes = GenericRelation(Vote, related_query_name="related_post")
    slug = models.SlugField(max_length=1024)
    doi = models.CharField(
        max_length=255, default=None, null=True, blank=True, unique=True
    )

    objects = ResearchhubPostQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["journey"],
                condition=Q(
                    document_type=REGISTERED_REPORT,
                    journey__isnull=False,
                ),
                name="unique_rr_per_journey",
            ),
        ]

    @property
    def is_latest_version(self):
        return self.next_version is None

    @property
    def is_root_version(self):
        return self.version_number == 1

    @cached_property
    def stage(self):
        return JOURNEY_STAGE_BY_DOCUMENT_TYPE.get(self.document_type)

    @property
    def users_to_notify(self):
        return [self.created_by]

    @property
    def paper(self):
        return None

    @property
    def hubs(self):
        return self.unified_document.hubs

    @property
    def is_removed(self):
        return self.unified_document.is_removed

    @property
    def hot_score(self):
        if not hasattr(self, "unified_document") or self.unified_document is None:
            return 0
        return self.unified_document.hot_score

    def get_document_slug_type(self):
        if self.document_type == "BOUNTY":
            return "bounty"
        elif self.document_type == "DISCUSSION":
            return "post"
        elif self.document_type == "QUESTION":
            return "question"

        return "post"

    def get_image_url(self):
        if not self.image:
            return None
        return default_storage.url(self.image)

    def get_promoted_score(self):
        purchases = self.purchases.filter(
            paid_status=Purchase.PAID, amount__gt=0, boost_time__gt=0
        )
        if purchases.exists():
            base_score = self.score
            boost_amount = (
                purchases.annotate(amount_as_int=Cast("amount", IntegerField()))
                .aggregate(sum=Sum("amount_as_int"))
                .get("sum", 0)
            )
            return base_score + boost_amount
        return False

    def get_boost_amount(self):
        purchases = self.purchases.filter(
            paid_status=Purchase.PAID, amount__gt=0, boost_time__gt=0
        )
        if purchases.exists():
            boost_amount = (
                purchases.annotate(amount_as_int=Cast("amount", IntegerField()))
                .aggregate(sum=Sum("amount_as_int"))
                .get("sum", 0)
            )
            return boost_amount
        return 0

    def get_full_markdown(self):
        try:
            if self.document_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                byte_string = self.discussion_src.read()
            else:
                byte_string = self.eln_src.read()
            full_markdown = byte_string.decode("utf-8")
            return full_markdown
        except Exception:
            logger.exception("Error getting full markdown for document %s", self.id)
            return None

    def get_discussion_count(self):
        return self.rh_threads.get_discussion_count()
