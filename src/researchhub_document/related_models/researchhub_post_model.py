import logging

from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.utils.functional import cached_property

from discussion.models import AbstractGenericReactionModel, Vote
from purchase.models import Grant
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

    def visible_to(
        self,
        user: User | None,
        shared_unified_document_id: int | None = None,
    ) -> "ResearchhubPostQuerySet":
        """Restrict to posts the given user is allowed to see.

        Anonymous users only see public posts that cleared moderation. Authors
        can see their own posts. Grant creators and document-permission users
        can see private posts after moderation clears; ``NO_ACCESS`` still wins.
        Moderators and hub editors can see all posts.

        Grant posts do not use unified-document moderation status. Their backing
        document stays approved, so ``Grant.status`` decides whether they cleared.

        ``shared_unified_document_id`` additionally admits the single document a
        valid share token was issued for. It is opt-in per call site so a share
        token can never widen discovery surfaces such as feeds: pass it only
        where a caller is serving that one document.
        """
        public = self._public_visibility_filter()
        # An empty Q is the neutral element of OR: Django drops it when
        # combining, so an absent token adds nothing to the filter.
        shared = (
            Q(unified_document_id=shared_unified_document_id)
            if shared_unified_document_id is not None
            else Q()
        )

        if user is None or not getattr(user, "is_authenticated", False):
            return self.filter(public | shared)

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
            public | shared | created_by_user | visible_to_grant_or_permitted
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
        through="ResearchhubPostAuthor",
        through_fields=("researchhub_post", "author"),
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
        max_length=2048,
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
    def paper(self):
        return None

    @property
    def hubs(self):
        return self.unified_document.hubs

    @property
    def is_removed(self):
        return self.unified_document.is_removed

    def get_image_url(self):
        if not self.image:
            return None
        return default_storage.url(self.image)

    def get_full_markdown(self):
        try:
            if self.document_type in RESEARCHHUB_POST_DOCUMENT_TYPES:
                src = self.discussion_src
            else:
                src = self.eln_src
            with src.open() as file:
                return file.read().decode("utf-8")
        except Exception:
            logger.exception("Error getting full markdown for document %s", self.id)
            return None

    def get_discussion_count(self):
        return self.rh_threads.get_discussion_count()


class ResearchhubPostAuthor(models.Model):
    researchhub_post = models.ForeignKey(
        ResearchhubPost,
        db_column="researchhubpost_id",
        on_delete=models.CASCADE,
    )
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    position = models.IntegerField()

    class Meta:
        db_table = "researchhub_document_researchhubpost_authors"
        constraints = [
            models.CheckConstraint(
                condition=Q(position__gte=1),
                name="researchhubpostauthor_position_positive",
            ),
            models.UniqueConstraint(
                fields=["researchhub_post", "position"],
                name="unique_researchhubpostauthor_position",
            ),
        ]
        unique_together = ("researchhub_post", "author")
