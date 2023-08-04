from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from user.models.author import Author


class Command(BaseCommand):
    """
    Backfills user author score for each author
    """

    def handle(self, *args, **options):
        authorset = Author.objects.all()
        total_authors = authorset.count()
        for i, author in enumerate(authorset):
            print("{} / {} / id: {}".format(i, total_authors, author.id))
            score = author.calculate_score()
            author.author_score = score
            author.save()
