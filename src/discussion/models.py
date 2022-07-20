from django.apps import apps
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.core.cache import cache
from django.db import models
from django.db.models import Count, F, Q
from django.utils.functional import cached_property

from hub.models import Hub
from paper.utils import get_cache_key
from purchase.models import Purchase
from researchhub.lib import CREATED_LOCATIONS
from researchhub_access_group.constants import EDITOR
from researchhub_access_group.models import Permission

from .reaction_models import AbstractGenericReactionModel, Flag, Vote

HELP_TEXT_WAS_EDITED = "True if the comment text was edited after first being created."
HELP_TEXT_IS_PUBLIC = "Hides the comment from the public."
HELP_TEXT_IS_REMOVED = "Hides the comment because it is not allowed."


class BaseComment(AbstractGenericReactionModel):
    CREATED_LOCATION_PROGRESS = CREATED_LOCATIONS["PROGRESS"]
    CREATED_LOCATION_CHOICES = [(CREATED_LOCATION_PROGRESS, "Progress")]

    DISCUSSION = "DISCUSSION"
    SUMMARY = "SUMMARY"
    REVIEW = "REVIEW"
    ANSWER = "ANSWER"

    DISCUSSION_POST_TYPE_CHOICES = (
        (DISCUSSION, DISCUSSION),
        (SUMMARY, SUMMARY),
        (REVIEW, REVIEW),
        (ANSWER, ANSWER),
    )

    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_date = models.DateTimeField(auto_now=True)
    created_location = models.CharField(
        choices=CREATED_LOCATION_CHOICES,
        max_length=255,
        default=None,
        null=True,
        blank=True,
    )
    discussion_post_type = models.CharField(
        default=DISCUSSION, choices=DISCUSSION_POST_TYPE_CHOICES, max_length=16
    )
    was_edited = models.BooleanField(default=False, help_text=HELP_TEXT_WAS_EDITED)
    is_public = models.BooleanField(default=True, help_text=HELP_TEXT_IS_PUBLIC)
    is_removed = models.BooleanField(default=False, help_text=HELP_TEXT_IS_REMOVED)
    ip_address = models.GenericIPAddressField(unpack_ipv4=True, blank=True, null=True)
    text = JSONField(blank=True, null=True)
    external_metadata = JSONField(null=True)
    plain_text = models.TextField(default="", blank=True)
    source = models.CharField(default="researchhub", max_length=32, null=True)
    purchases = GenericRelation(
        Purchase,
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="discussion",
    )
    contributions = GenericRelation(
        "reputation.Contribution",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="discussion",
    )

    class Meta:
        abstract = True

    # TODO make this a mixin Actionable or Notifiable
    @property
    def owners(self):
        if self.created_by:
            return [self.created_by]
        else:
            return []

    # TODO make this a mixin Actionable or Notifiable
    @property
    def users_to_notify(self):
        parent_owners = self.parent.owners
        return parent_owners

    @property
    def created_by_author_profile_indexing(self):
        if self.created_by:
            author = self.created_by.author_profile
            if author:
                return author
        return None

    @property
    def children(self):
        return BaseComment.objects.none()

    @property
    def is_created_by_editor(self):
        uni_doc = self.unified_document
        if uni_doc is not None:
            return Permission.objects.filter(
                access_type=EDITOR,
                user=self.created_by,
                content_type=ContentType.objects.get_for_model(Hub),
                object_id__in=uni_doc.hubs.values_list("id", flat=True),
            ).exists()
        return False

    def update_discussion_count(self):
        paper = self.paper
        if paper:
            new_dis_count = paper.get_discussion_count()
            paper.calculate_hot_score()

            paper.discussion_count = new_dis_count
            paper.save(update_fields=["discussion_count"])

            cache_key = get_cache_key("paper", paper.id)
            cache.delete(cache_key)

            for h in paper.hubs.all():
                h.discussion_count = h.get_discussion_count()
                h.save(update_fields=["discussion_count"])

            return new_dis_count

        post = self.post
        hypothesis = self.hypothesis
        instance = post or hypothesis
        if instance:
            new_dis_count = instance.get_discussion_count()
            instance.discussion_count = new_dis_count
            instance.save()
            return new_dis_count

        return 0

    def remove_nested(self):
        if self.is_removed is False:
            self.is_removed = True
            self.save(update_fields=["is_removed"])
        if len(self.children) > 0:
            for c in self.children:
                c.remove_nested()

    def get_promoted_score(self):
        purchases = self.purchases.filter(
            paid_status=Purchase.PAID,
        )
        if purchases.exists():
            boost_score = sum(map(int, purchases.values_list("amount", flat=True)))
            return boost_score
        return False

    def get_all_doc_contributors(self):
        if self.paper is not None:
            threads = Thread.objects.filter(paper_id=self.paper.id).values(
                "created_by", "id"
            )
            thread_ids = list(map(lambda t: t["id"], threads))
        elif self.post is not None:
            threads = Thread.objects.filter(post_id=self.post.id).values(
                "created_by", "id"
            )
            thread_ids = list(map(lambda t: t["id"], threads))
        elif self.hypothesis is not None:
            threads = Thread.objects.filter(hypothesis_id=self.hypothesis.id).values(
                "created_by", "id"
            )
            thread_ids = list(map(lambda t: t["id"], threads))
        else:
            return []

        comments = Comment.objects.filter(parent_id__in=thread_ids).values(
            "created_by_id", "id"
        )
        comment_ids = list(map(lambda c: c["id"], comments))

        replies = Reply.objects.filter(object_id__in=comment_ids).values(
            "created_by_id", "id"
        )

        contributor_ids = (
            list(map(lambda t: t["created_by"], threads))
            + list(map(lambda t: t["created_by_id"], comments))
            + list(map(lambda t: t["created_by_id"], replies))
        )

        User = apps.get_model("user", "User")
        users = User.objects.filter(id__in=contributor_ids)

        return users


class Thread(BaseComment):
    CITATION_COMMENT = "citation_comment"
    INLINE_ABSTRACT = "inline_abstract"
    INLINE_PAPER_BODY = "inline_paper_body"
    RESEARCHHUB = "researchhub"
    THREAD_SOURCE_CHOICES = [
        (CITATION_COMMENT, "Citation Comment"),
        (INLINE_ABSTRACT, "Inline Abstract"),
        (INLINE_PAPER_BODY, "Inline Paper Body"),
        (RESEARCHHUB, "researchhub"),
    ]
    source = models.CharField(
        default=RESEARCHHUB, choices=THREAD_SOURCE_CHOICES, max_length=32
    )
    block_key = models.CharField(max_length=255, null=True, blank=True)
    context_title = models.TextField(
        blank=True,
        null=True,
        help_text="For inline-comments, indicates what's highlighted",
    )
    entity_key = models.CharField(max_length=255, null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    paper = models.ForeignKey(
        "paper.Paper",
        on_delete=models.SET_NULL,
        related_name="threads",
        blank=True,
        null=True,
    )
    post = models.ForeignKey(
        "researchhub_document.ResearchhubPost",
        on_delete=models.SET_NULL,
        related_name="threads",
        blank=True,
        null=True,
    )
    hypothesis = models.ForeignKey(
        "hypothesis.Hypothesis",
        on_delete=models.SET_NULL,
        related_name="threads",
        null=True,
        blank=True,
    )
    citation = models.ForeignKey(
        "hypothesis.Citation",
        on_delete=models.SET_NULL,
        related_name="threads",
        null=True,
        blank=True,
    )
    peer_review = models.ForeignKey(
        "peer_review.PeerReview",
        on_delete=models.SET_NULL,
        related_name="threads",
        blank=True,
        null=True,
    )
    review = models.ForeignKey(
        "review.Review",
        on_delete=models.SET_NULL,
        related_name="thread",
        blank=True,
        null=True,
    )
    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="threads",
    )

    def __str__(self):
        return "%s: %s" % (self.created_by, self.title)

    @cached_property
    def parent(self):
        return self.paper

    @cached_property
    def unified_document(self):
        paper = self.paper
        if paper:
            return paper.unified_document

        post = self.post
        if post:
            return post.unified_document

        hypothesis = self.hypothesis
        if hypothesis:
            return hypothesis.unified_document

        peer_review = self.peer_review
        if peer_review:
            return peer_review.unified_document

        citation = self.citation
        if citation:
            return citation.source

        return None

    @property
    def children(self):
        return self.comments.filter(is_removed=False)

    @property
    def comment_count_indexing(self):
        return len(self.comments.filter(is_removed=False))

    @property
    def paper_indexing(self):
        if self.paper is not None:
            return self.paper.id

    @property
    def paper_title_indexing(self):
        if self.paper is not None:
            return self.paper.title

    @property
    def owners(self):
        if (
            self.created_by
            and self.created_by.emailrecipient.thread_subscription
            and not self.created_by.emailrecipient.thread_subscription.none
        ):
            return [self.created_by]
        else:
            return []

    @property
    def users_to_notify(self):
        users = []
        if self.paper is not None:
            # users = list(self.parent.moderators.all())
            paper_authors = self.parent.authors.all()
            for author in paper_authors:
                if author.user:
                    users.append(author.user)

            if self.paper.uploaded_by is not None:
                users.append(self.paper.uploaded_by)

        elif self.post is not None:
            users.append(self.post.created_by)
        elif self.hypothesis is not None:
            users.append(self.hypothesis.created_by)

        contributors = self.get_all_doc_contributors()
        users = list(set(users + list(contributors)))

        # Remove person who made comment
        users = [u for u in users if u.id != self.created_by.id]

        return users


class Reply(BaseComment):
    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, blank=True, null=True
    )
    object_id = models.PositiveIntegerField()
    parent = GenericForeignKey("content_type", "object_id")
    replies = GenericRelation("Reply")
    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="replies",
    )

    @cached_property
    def paper(self):
        comment = self.get_comment_of_reply()
        paper = comment.paper
        return paper

    @cached_property
    def post(self):
        comment = self.get_comment_of_reply()
        if comment:
            post = comment.post
            return post

    @cached_property
    def hypothesis(self):
        comment = self.get_comment_of_reply()
        if comment:
            hypothesis = comment.hypothesis
            return hypothesis

    @cached_property
    def thread(self):
        comment = self.get_comment_of_reply()
        thread = comment.parent
        return thread

    @cached_property
    def unified_document(self):
        thread = self.thread
        paper = thread.paper
        hypothesis = thread.hypothesis

        if paper:
            return paper.unified_document

        post = thread.post
        if post:
            return post.unified_document

        hypothesis = thread.hypothesis
        if hypothesis:
            return hypothesis.unified_document

        return None

    @property
    def children(self):
        return self.replies.filter(is_removed=False)

    def get_comment_of_reply(self):
        obj = self
        while isinstance(obj, Reply):
            obj = obj.parent

        if isinstance(obj, Comment):
            return obj
        return None

    @property
    def owners(self):
        return [self.created_by]

    @property
    def users_to_notify(self):
        users = []
        p = self.parent
        if isinstance(p, Reply):
            if p.created_by and not p.created_by == self.created_by:
                users.append(p.created_by)
        else:
            if p.created_by:
                users.append(p.created_by)

        if self.paper is not None and self.paper.uploaded_by is not None:
            users.append(self.paper.uploaded_by)
        elif self.post is not None:
            users.append(self.post.created_by)
        elif self.hypothesis is not None:
            users.append(self.hypothesis.created_by)

        # This will ensure everyone who contributed a comment, reply or thread
        # gets notified. Will need to likely turn off once we have
        # lots of activity on papers/posts/hypothesis
        contributors = self.get_all_doc_contributors()
        users = list(set(users + list(contributors)))

        # Remove person who made comment
        users = [u for u in users if u.id != self.created_by.id]

        return users


class Comment(BaseComment):
    parent = models.ForeignKey(
        Thread,
        on_delete=models.SET_NULL,
        related_name="comments",
        blank=True,
        null=True,
    )
    replies = GenericRelation(Reply)
    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="comments",
    )

    def __str__(self):
        return "{} - {}".format(self.created_by, self.plain_text)

    @cached_property
    def paper(self):
        thread = self.parent
        if thread:
            paper = thread.paper
            return paper

    @cached_property
    def post(self):
        thread = self.parent
        if thread:
            post = thread.post
            return post

    @cached_property
    def hypothesis(self):
        thread = self.parent
        if thread:
            hypothesis = thread.hypothesis
            return hypothesis

    @cached_property
    def unified_document(self):
        thread = self.thread
        paper = thread.paper
        if paper:
            return paper.unified_document

        post = thread.post
        if post:
            return post.unified_document

        hypothesis = thread.hypothesis
        if hypothesis:
            return hypothesis.unified_document

        return None

    @cached_property
    def thread(self):
        thread = self.parent
        return thread

    @property
    def children(self):
        return self.replies.filter(is_removed=False)

    @property
    def owners(self):
        return [self.created_by]

    @property
    def users_to_notify(self):
        users = []
        p = self.parent
        if p.created_by and not p.created_by == self.created_by:
            users.append(p.created_by)

        if self.paper is not None and self.paper.uploaded_by is not None:
            users.append(self.paper.uploaded_by)
        elif self.post is not None:
            users.append(self.post.created_by)
        elif self.hypothesis is not None:
            users.append(self.hypothesis.created_by)

        # This will ensure everyone who contributed a comment, reply or thread
        # gets notified. Will need to likely turn off once we have
        # lots of activity on papers/posts/hypothesis
        contributors = self.get_all_doc_contributors()
        users = list(set(users + list(contributors)))

        # Remove person who made comment
        users = [u for u in users if u.id != self.created_by.id]

        return users
