from django.core.management.base import BaseCommand
from django.db import transaction

from researchhub_comment.models import RhCommentModel, RhCommentThreadModel


class Command(BaseCommand):
    def handle(self, *args, **options):
        comments = RhCommentModel.objects.all()
        with transaction.atomic():
            for i, comment in enumerate(comments):
                comment.comment_type = comment.thread.thread_type
                comment.save()
