from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from discussion.models import Comment, Reply, Thread
from hub.models import Hub
from paper.models import Paper
from researchhub.settings import BASE_FRONTEND_URL, TESTING
from summary.models import Summary
from user.related_models.user_model import User
from utils.models import DefaultModel


class Action(DefaultModel):
    user = models.ForeignKey(
        User,
        related_name='actions',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey('content_type', 'object_id')
    display = models.BooleanField(default=True)
    read_date = models.DateTimeField(default=None, null=True)
    hubs = models.ManyToManyField(
        Hub,
        related_name='actions',
    )

    def __str__(self):
        return 'Action: {}-{}-{}, '.format(
            self.content_type.app_label,
            self.content_type.model,
            self.object_id
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
        if (
            not hasattr(act.item, 'created_by')
            and hasattr(act.item, 'proposed_by')
        ):
            act.item.created_by = act.item.proposed_by

        if (
            hasattr(act, 'content_type')
            and act.content_type
            and act.content_type.name
        ):
            act.content_type_name = act.content_type.name
        else:
            act.content_type_name = 'paper'

        verb = 'done a noteworthy action on'
        if act.content_type_name == 'reply':
            verb = 'replied to'
        elif act.content_type_name == 'comment':
            verb = 'commented on'
        elif act.content_type_name == 'summary':
            verb = 'edited'
        elif act.content_type_name == 'thread':
            verb = 'created a new discussion on'

        noun = 'paper'
        if act.content_type_name == 'comment':
            noun = 'thread'
        elif act.content_type_name == 'reply':
            noun = 'comment on'
        elif act.content_type_name == 'thread':
            noun = 'paper'

        act.label = 'has {} the {}'.format(verb, noun)

        if act.content_type_name == 'summary':
            act.label += ' summary'

        return act

    @property
    def frontend_view_link(self):
        link = BASE_FRONTEND_URL
        if isinstance(self.item, Summary):
            link += '/paper/{}/'.format(self.item.paper.id)
        elif isinstance(self.item, Paper):
            link += '/paper/{}/'.format(self.item.id)
        elif isinstance(self.item, Thread):
            link += '/paper/{}/discussion/{}'.format(
                self.item.paper.id,
                self.item.id
            )
        elif isinstance(self.item, Comment):
            link += '/paper/{}/discussion/{}'.format(
                self.item.paper.id,
                self.item.thread.id
            )
        elif isinstance(self.item, Reply):
            link += '/paper/{}/discussion/{}'.format(
                self.item.paper.id,
                self.item.thread.id,
            )
        else:
            raise Exception('frontend_view_link not implemented')
        return link
