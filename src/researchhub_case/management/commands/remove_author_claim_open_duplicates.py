from django.core.management.base import BaseCommand

from user.models import User
from researchhub_case.models import AuthorClaimCase
from researchhub_case.constants.case_constants import AUTHOR_CLAIM, OPEN


class Command(BaseCommand):

    def handle(self, *args, **options):
        case_creators = User.objects.filter(
          created_cases__isnull=False,
          case_type=AUTHOR_CLAIM
        )

        try:
            for case_creator in case_creators.iterator():
                created_cases = case_creator.created_cases.filter(status=OPEN)
                for target_case in created_cases.iterator():
                    AuthorClaimCase.objects.filter(
                      id__isnot=target_case.id,
                      status=OPEN,
                      target_author=target_case.target_author,
                    ).delete()
        except Exception as error:
            print(error)
