"""
Adds slug to papers
"""

from django.core.management.base import BaseCommand

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
