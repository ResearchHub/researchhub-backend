from django.core.management.base import BaseCommand
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider

from user.tasks import link_author_to_papers


class Command(BaseCommand):

    def handle(self, *args, **options):
        orcid_accounts = SocialAccount.objects.filter(
            provider=OrcidProvider.id
        )
        for orcid_account in orcid_accounts:
            author = orcid_account.user.author_profile
            link_author_to_papers(author.id, orcid_account.id)
