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
        citations = CitationProject.objects.all()
        count = citations.count()

        for i, instance in enumerate(citations.iterator()):
            print(f"{i}/{count}")
            parent_name_object = instance.get_parent_name(instance, [], [])
            instance.parent_names = parent_name_object
            instance.save()
