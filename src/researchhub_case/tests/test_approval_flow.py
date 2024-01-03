from django.test import TestCase

from paper.tests.helpers import create_paper
from researchhub_case.constants.case_constants import APPROVED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.tasks import after_approval_flow
from user.tests.helpers import create_moderator, create_random_default_user
from user.utils import move_paper_to_author


class ApprovalFlowTests(TestCase):
    def setUp(self):
        self.paper = create_paper(
            title="some title",
            uploaded_by=None,
            raw_authors='[{"first_name": "jane", "last_name": "smith"}]',
        )

    def test_mark_user_verified_after_approval(self):
        requesting_user = create_random_default_user("1")
        case = AuthorClaimCase.objects.create(
            target_paper=self.paper, requestor=requesting_user, status=APPROVED
        )

        after_approval_flow(case.id)
        requesting_user.refresh_from_db()
        self.assertEquals(requesting_user.is_verified, True)

    def attribute_paper_to_author(self):
        requesting_user = create_random_default_user("2")
        case = AuthorClaimCase.objects.create(
            target_paper=self.paper, requestor=requesting_user, status=APPROVED
        )

        after_approval_flow(case.id)
        requesting_user.refresh_from_db()
        self.paper.refresh_from_db()
        self.assertEquals(self.paper.authors.first().id, requesting_user.id)
