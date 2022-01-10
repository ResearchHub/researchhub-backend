from django.core.management.base import BaseCommand
from django.db.models import Q

from user.models import User
from researchhub_case.models import AuthorClaimCase
from researchhub_case.constants.case_constants import AUTHOR_CLAIM, OPEN


class Command(BaseCommand):

    def handle(self, *args, **options):
        case_creators = User.objects.filter(
          created_cases__isnull=False,
          created_cases__case_type=AUTHOR_CLAIM
        )

        try:
            for case_creator in case_creators.iterator():
                created_cases = case_creator.created_cases.filter(status=OPEN)
                for target_case in created_cases.iterator():
                    print("Deleting duplicates for id: ", target_case.id)
                    try:
                        AuthorClaimCase.objects.filter(
                          ~Q(id=target_case.id),
                          status=OPEN,
                          target_author=target_case.target_author,
                        ).delete()
                    except Exception as error:
                        print(error)
                        pass
        except Exception as error:
            print(error)
            pass

        print("Script remove_author_claim_open_duplicates finished")
