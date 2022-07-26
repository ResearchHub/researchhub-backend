from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.utils import timezone

from discussion.models import Comment, Reply, Thread
from hub.models import Hub
from paper.models import Paper, PaperSubmission
from reputation.models import Bounty, Withdrawal
from researchhub.settings import BASE_FRONTEND_URL, TESTING
from summary.models import Summary
from user.related_models.user_model import User
from utils.models import DefaultModel


class Action(DefaultModel):
    user = models.ForeignKey(
        User, related_name="actions", on_delete=models.SET_NULL, null=True, blank=True
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")
    display = models.BooleanField(default=True)
    read_date = models.DateTimeField(default=None, null=True)
    hubs = models.ManyToManyField(
        Hub,
        related_name="actions",
    )

    class Meta:
        ordering = ["-created_date"]
        indexes = (
            models.Index(
                fields=("user",),
                condition=models.Q(user=None),
                name="user_action_user_null_ix",
            ),
            BrinIndex(
                fields=("created_date",),
                pages_per_range=2,
                name="user_action_createdate_brin_ix",
            ),
        )

    def __str__(self):
        return "Action: {}-{}-{}, ".format(
            self.content_type.app_label, self.content_type.model, self.object_id
        )

    def save(self, *args, **kwargs):
        if self.id is None:
            from mailing_list.tasks import notify_immediate

            super().save(*args, **kwargs)
            if not TESTING:
                notify_immediate.apply_async((self.id,), priority=5)
            else:
                notify_immediate(self.id)
        else:
            super().save(*args, **kwargs)

    def set_read(self):
        self.read_date = timezone.now()
        self.save()

    def email_context(self):
        act = self
        if not hasattr(act.item, "created_by") and hasattr(act.item, "proposed_by"):
            act.item.created_by = act.item.proposed_by

        if hasattr(act, "content_type") and act.content_type and act.content_type.name:
            act.content_type_name = act.content_type.name

        verb = "done a noteworthy action on"
        if act.content_type_name == "reply":
            verb = "replied to"
        elif act.content_type_name == "comment":
            verb = "commented on"
        elif act.content_type_name == "summary":
            verb = "edited"
        elif act.content_type_name == "thread":
            verb = "created a new discussion on"
        elif act.content_type_name == "hypothesis":
            verb = "created a new hypothesis on"
        elif act.content_type_name == "researchhub post":
            verb = "created a new post on"
        elif act.content_type_name == "paper":
            verb = "uploaded a new paper"

        noun = ""
        if act.content_type_name == "comment":
            noun = "the thread"
        elif act.content_type_name == "reply":
            noun = "comment on"
        elif act.content_type_name == "thread":
            noun = self.doc_type

        act.label = "has {} {}".format(verb, noun)

        if act.content_type_name == "summary":
            act.label += " summary"

        if isinstance(act.item, Bounty):
            act.message = "Your bounty is expiring in one day! If you have a suitable answer, make sure to pay out your bounty in order to keep your reputation on ResearchHub high."

        return act

    @property
    def doc_type(self):
        doc_type = ""
        try:
            doc_type = self.item.unified_document.document_type
            if doc_type == "DISCUSSION":
                doc_type = "post"
            elif doc_type == "HYPOTHESIS":
                doc_type = "hypothesis"
            elif doc_type == "PAPER":
                doc_type = "paper"
        except Exception:
            doc_type = ""

        return doc_type

    @property
    def title(self):
        title = ""
        try:
            title = self.item.unified_document.get_document().title
        except Exception as e:
            title = ""

        return title

    @property
    def created_by(self):
        created_by = None
        try:
            doc_type = self.item.unified_document.document_type
            if doc_type == "DISCUSSION":
                created_by = self.item.created_by
            elif doc_type == "HYPOTHESIS":
                created_by = self.item.created_by
            elif doc_type == "PAPER":
                created_by = self.item.uploaded_by
        except Exception as e:
            return None

        return created_by

    @property
    def doc_summary(self):
        SUMMARY_MAX_LEN = 256
        summary = ""
        try:
            item = self.item
            if isinstance(item, (Thread, Comment, Reply)):
                summary = item.plain_text
            else:
                doc_type = item.unified_document.document_type
                if doc_type == "DISCUSSION":
                    summary = self.item.renderable_text
                elif doc_type == "HYPOTHESIS":
                    summary = self.item.renderable_text
                elif doc_type == "PAPER":
                    summary = self.item.abstract
        except Exception as e:
            return ""

        if summary and len(summary) > SUMMARY_MAX_LEN:
            summary = f"{summary[:SUMMARY_MAX_LEN]} ..."
        else:
            summary = ""
        return summary

    @property
    def frontend_view_link(self):
        from hypothesis.models import Hypothesis
        from researchhub_document.models import ResearchhubPost

        link = BASE_FRONTEND_URL
        item = self.item

        if isinstance(item, Bounty):
            item = item.item.get_document()

        if isinstance(item, Summary):
            link += "/paper/{}/".format(item.paper.id)
        elif isinstance(item, Paper):
            link += "/paper/{}/".format(item.id)
        elif (
            isinstance(item, Thread)
            or isinstance(item, Comment)
            or isinstance(item, Reply)
        ):
            doc_type = self.item.unified_document.document_type
            if doc_type == "DISCUSSION" or doc_type == "QUESTION":
                link += "/post/{}/{}#comments".format(item.post.id, item.post.slug)
            elif doc_type == "HYPOTHESIS":
                link += "/hypothesis/{}/{}#comments".format(
                    item.hypothesis.id, item.hypothesis.slug
                )
            else:
                link += "/paper/{}/{}#comments".format(item.paper.id, item.paper.slug)

        elif isinstance(item, ResearchhubPost):
            link += "/post/{}/{}".format(item.id, item.title)
        elif isinstance(item, Hypothesis):
            link += "/hypothesis/{}/{}".format(item.id, item.title)
        elif isinstance(item, Withdrawal):
            link = ""
        elif isinstance(item, PaperSubmission):
            link = ""
        else:
            raise Exception("frontend_view_link not implemented")
        return link
