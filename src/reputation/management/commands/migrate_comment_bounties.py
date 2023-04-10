import os

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from discussion.models import Thread
from reputation.models import Bounty
from researchhub_comment.models import RhCommentModel


class Command(BaseCommand):
    def handle(self, *args, **options):
        bounty_threads = Bounty.objects.filter(
            item_content_type=ContentType.objects.get_for_model(Thread)
        )
        count = bounty_threads.count()
        for i, bounty in enumerate(bounty_threads):
            print("{} / {}".format(i, count))
            new_comment = RhCommentModel.objects.filter(legacy_id=bounty.item_object_id)
            if new_comment.exists():
                new_comment = new_comment.first()
                bounty.item_object_id = new_comment.id
                bounty.item_content_type = ContentType.objects.get_for_model(
                    RhCommentModel
                )
                bounty.save()
