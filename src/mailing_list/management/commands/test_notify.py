from django.core.management.base import BaseCommand

from discussion.tests.helpers import create_thread
from paper.tests.helpers import create_paper
from user.models import User
from user.tests.helpers import create_random_authenticated_user


class Command(BaseCommand):

    def handle(self, *args, **options):
        alice = create_random_authenticated_user('alice')
        paper = create_paper()
        paper.authors.add(alice.author_profile)
        alice.emailrecipient.paper_subscription.none = True
        alice.emailrecipient.paper_subscription.save()
        bob = create_random_authenticated_user('bob')
        create_thread(paper=paper, created_by=bob)

        User.objects.get(pk=alice.id).delete()
        User.objects.get(pk=bob.id).delete()
