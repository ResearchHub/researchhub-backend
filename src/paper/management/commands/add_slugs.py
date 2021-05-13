'''
Adds slug to papers
'''
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils.text import slugify
from django.utils.crypto import get_random_string

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        papers = Paper.objects.filter(
            Q(slug__isnull=True) | Q(slug='')
        )
        count = papers.count()

        for i, paper in enumerate(papers.iterator()):
            print(f'{i}/{count}')
            title = paper.paper_title or paper.title
            suffix = get_random_string(length=32)
            slug = slugify(title)

            if not slug:
                slug += suffix

            paper.slug = slug
            paper.save()
