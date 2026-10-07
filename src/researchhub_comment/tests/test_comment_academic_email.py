from allauth.account.models import EmailAddress
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from researchhub_comment.models import RhCommentModel
from researchhub_comment.tests.helpers import create_rh_comment
from user.tests.helpers import create_random_default_user, create_user

STANFORD_BADGE = {
    "email_domain": "cs.stanford.edu",
    "institution_domain": "stanford.edu",
    "source": "account_email",
}


def _create_academic_user(email):
    user = create_user(email=email)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    return user


def _create_reply(parent, created_by):
    return RhCommentModel.objects.create(
        comment_content_json={"text": "reply"},
        thread=parent.thread,
        parent=parent,
        created_by=created_by,
        updated_by=created_by,
    )


def _count_academic_email_queries(captured):
    return sum(
        1
        for query in captured.captured_queries
        if "socialaccount_socialaccount" in query["sql"]
        or "account_emailaddress" in query["sql"]
    )


class CommentAcademicEmailTests(APITestCase):
    def setUp(self):
        self.academic_user = _create_academic_user("jdoe@cs.stanford.edu")
        self.plain_user = create_random_default_user("plain_commenter")
        self.paper = create_paper(uploaded_by=self.plain_user)
        self.comments_url = f"/api/paper/{self.paper.id}/comments/"

    def test_list_includes_badge_for_comment_and_reply_authors(self):
        # Arrange
        parent = create_rh_comment(paper=self.paper, created_by=self.academic_user)
        _create_reply(parent, self.plain_user)

        # Act
        response = self.client.get(self.comments_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        [comment] = response.data["results"]
        [reply] = comment["children"]
        self.assertEqual(
            comment["created_by"]["verified_academic_email"], STANFORD_BADGE
        )
        self.assertIsNone(reply["created_by"]["verified_academic_email"])

    def test_retrieve_includes_badge(self):
        # Arrange
        comment = create_rh_comment(paper=self.paper, created_by=self.academic_user)

        # Act
        response = self.client.get(f"{self.comments_url}{comment.id}/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["created_by"]["verified_academic_email"], STANFORD_BADGE
        )

    def test_create_response_includes_badge(self):
        # Arrange
        self.client.force_authenticate(self.academic_user)

        # Act
        response = self.client.post(
            f"{self.comments_url}create_rh_comment/",
            {"comment_content_json": {"ops": [{"insert": "hello"}]}},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["created_by"]["verified_academic_email"], STANFORD_BADGE
        )

    def test_never_exposes_the_email_address(self):
        # Arrange
        create_rh_comment(paper=self.paper, created_by=self.academic_user)

        # Act
        response = self.client.get(self.comments_url)

        # Assert
        self.assertNotIn("jdoe@", str(response.data))

    def test_list_query_count_does_not_grow_with_comment_authors(self):
        # Arrange
        create_rh_comment(paper=self.paper, created_by=self.academic_user)
        with CaptureQueriesContext(connection) as one_author:
            self.client.get(self.comments_url)
        for i in range(3):
            create_rh_comment(
                paper=self.paper,
                created_by=_create_academic_user(f"author{i}@mit.edu"),
            )

        # Act
        with CaptureQueriesContext(connection) as many_authors:
            response = self.client.get(self.comments_url)

        # Assert
        self.assertEqual(len(response.data["results"]), 4)
        self.assertEqual(
            _count_academic_email_queries(many_authors),
            _count_academic_email_queries(one_author),
        )

    def test_reply_query_count_does_not_grow_with_reply_authors(self):
        # Arrange
        parent = create_rh_comment(paper=self.paper, created_by=self.plain_user)
        _create_reply(parent, self.academic_user)
        with CaptureQueriesContext(connection) as one_author:
            self.client.get(self.comments_url)
        for i in range(3):
            _create_reply(parent, _create_academic_user(f"replier{i}@mit.edu"))

        # Act
        with CaptureQueriesContext(connection) as many_authors:
            response = self.client.get(self.comments_url)

        # Assert
        self.assertEqual(len(response.data["results"][0]["children"]), 4)
        self.assertEqual(
            _count_academic_email_queries(many_authors),
            _count_academic_email_queries(one_author),
        )
