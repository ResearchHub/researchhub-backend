from django.core.management.base import BaseCommand
from django.db.models import Q

from researchhub_case.constants.case_constants import AUTHOR_CLAIM, OPEN
from researchhub_case.models import AuthorClaimCase
from user.models import User


class Command(BaseCommand):
    def handle(self, *args, **options):
        open_case_requestors = User.objects.filter(
            authorclaimcase_requested_cases__isnull=False,
            authorclaimcase_requested_cases__case_type=AUTHOR_CLAIM,
            authorclaimcase_requested_cases__status=OPEN,
        ).distinct()
        case_ids_to_not_delete = []
        try:
            for case_requestor in open_case_requestors.iterator():
                open_cases = case_requestor.created_cases.filter(status=OPEN)
                for target_case in open_cases.iterator():
                    original_case_id = target_case.id
                    try:
                        AuthorClaimCase.objects.filter(
                            ~Q(id=original_case_id),
                            ~Q(id__in=case_ids_to_not_delete),
                            requestor=case_requestor,
                            status=OPEN,
                            target_author=target_case.target_author,
                        ).delete()
                        case_ids_to_not_delete.append(original_case_id)
                    except Exception as error:
                        print(error)
                        pass
        except Exception as error:
            print(error)
            pass

        print("Script remove_author_claim_open_duplicates finished")
