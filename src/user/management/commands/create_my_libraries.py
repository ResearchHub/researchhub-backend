from django.core.management.base import BaseCommand

from citation.models import CitationProject
from user.models import Organization, User


class Command(BaseCommand):
    """
    Creates organizations for all pre-existing users
    """

    def handle(self, *args, **options):
        orgs = Organization.objects.all()
        org_count = orgs.count()
        for i, org in enumerate(orgs):
            print(f"{i} / {org_count}")
            if not CitationProject.objects.filter(
                organization=org, slug="my-library"
            ).exists():
                if org.user:
                    project = CitationProject.objects.create(
                        is_public=True,
                        slug="my-library",
                        project_name="My Library",
                        parent_names={"names": ["My Library"], "slugs": ["my-library"]},
                        organization=org,
                        created_by=org.user,
                    )
                    project.set_creator_as_admin()
