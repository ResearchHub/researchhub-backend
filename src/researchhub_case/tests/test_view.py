from rest_framework.test import APITestCase
from paper.tests.helpers import create_paper
from user.tests.helpers import (
    create_random_default_user,
    create_author
)
from user.models import Author
from researchhub_case.models import AuthorClaimCase


class ViewTests(APITestCase):
    def setUp(self):
      self.paper = create_paper(
        title='some title',
        uploaded_by=None,
        raw_authors='[{"first_name": "jane", "last_name": "smith"}]'
      )


    def test_claimed_profiles_cannot_be_reclaimed(self):
      author = Author.objects.create(
        first_name="jane",
        last_name="smith",
      )

      claiming_user = create_random_default_user('claiming_user')
      claiming_user2 = create_random_default_user('claiming_user2')

      self.client.force_authenticate(claiming_user)
      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"AUTHOR_CLAIM",
          "creator": claiming_user.id,
          "requestor":claiming_user.id,
          "provided_email":"example@example.com",
          "context_content_type":"paper",
          "context_content_id": self.paper.id,
          "author":{
            "first_name":"jane",
            "last_name":"smith",
          }
        }
      )

      # Mark author as claimed
      claim = AuthorClaimCase.objects.get(id=response.data['id'])
      claim.status = 'APPROVED'
      claim.save()

      author.claimed = True
      author.save()

      # User 2 attempts to claim
      self.client.force_authenticate(claiming_user2)
      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"AUTHOR_CLAIM",
          "creator": claiming_user2.id,
          "requestor":claiming_user2.id,
          "provided_email":"example@example.com",
          "context_content_type":"paper",
          "context_content_id": self.paper.id,
          "author":{
            "first_name":"jane",
            "last_name":"smith",
          }
        }
      )

      self.assertGreaterEqual(response.status_code, 400)


    def test_claim_without_context_is_ok_too(self):
      author = Author.objects.create(
        first_name="jane",
        last_name="smith",
      )

      claiming_user = create_random_default_user('claiming_user')

      self.client.force_authenticate(claiming_user)
      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"AUTHOR_CLAIM",
          "creator": claiming_user.id,
          "requestor":claiming_user.id,
          "provided_email":"example@example.com",
          "author":{
            "first_name":"jane",
            "last_name":"smith",
          }
        }
      )

      self.assertTrue('id' in response.data)


