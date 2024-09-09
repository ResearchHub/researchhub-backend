"""
Adds slug to papers
"""

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from citation.models import CitationProject


class Command(BaseCommand):
    def handle(self, *args, **options):
        citations = CitationProject.objects.filter(Q(slug__isnull=True) | Q(slug=""))
        count = citations.count()

        for i, instance in enumerate(citations.iterator()):
            print(f"{i}/{count}")
            suffix = get_random_string(length=32)
            slug = slugify(instance.project_name)
            if not slug:
                slug += suffix
            if not CitationProject.objects.filter(slug=slug).exists():
                instance.slug = slug
            else:
                instance.slug = slug + "-" + suffix
            instance.save()
