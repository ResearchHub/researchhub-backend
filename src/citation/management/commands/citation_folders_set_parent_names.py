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
        def get_parent_name(citation_folder, names=[], slugs=[]):
            if not citation_folder.parent:
                return {"names": names, "slugs": slugs}
            else:
                names.append(citation_folder.project_name)
                slugs.append(citation_folder.slug)
                return get_parent_name(citation_folder.parent, names, slugs)

        citations = CitationProject.objects.all()
        count = citations.count()

        for i, instance in enumerate(citations.iterator()):
            print(f"{i}/{count}")
            # suffix = get_random_string(length=32)
            # slug = slugify(instance.project_name)

            # if not slug:
            #     slug += suffix
            # if not CitationProject.objects.filter(slug=slug).exists():
            #     instance.slug = slug
            # else:
            #     instance.slug = slug + "_" + suffix
            parent_name_object = get_parent_name(instance, [], [])
            instance.parent_names = parent_name_object
            instance.save()
