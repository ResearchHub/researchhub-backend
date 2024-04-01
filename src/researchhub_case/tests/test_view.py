from rest_framework.test import APITestCase
from paper.tests.helpers import create_paper
from user.tests.helpers import (
    create_random_default_user,
    create_moderator,
)
from researchhub_case.models import AuthorClaimCase
from researchhub_case.constants.case_constants import PAPER_CLAIM

class ViewTests(APITestCase):
    def setUp(self):
      self.paper = create_paper(
        title='some title',
        uploaded_by=None,
        raw_authors='[{"first_name": "jane", "last_name": "smith"}]'
      )

    def test_approved_claim_moves_paper_to_author(self):
      moderator = create_moderator(first_name='moderator', last_name='moderator')
      claiming_user = create_random_default_user('claiming_user')
      self.client.force_authenticate(claiming_user)

      paper = create_paper(
        title='some title',
        uploaded_by=None,
      )

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user.id,
          "requestor":claiming_user.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper.id,
          "target_author_name": "some paper author",
        }
      )

      self.assertEqual(response.status_code, 201)

      # Update Claim status
      claim = AuthorClaimCase.objects.get(id=response.data['id'])
      claim.status = 'OPEN'
      claim.save()

      # Approve claim
      self.client.force_authenticate(moderator)
      update_response = self.client.post(
        "/api/author_claim_case/moderator/", {
          "case_id": response.data['id'],
          "notify_user": True,
          "update_status": 'APPROVED',
        }
      )

      self.assertEqual(update_response.status_code, 200)

      claim = AuthorClaimCase.objects.get(id=response.data['id'])
      self.assertEqual(claim.status, 'APPROVED')
      self.assertTrue(paper in claiming_user.author_profile.authored_papers.all())

    def test_approved_claim_moves_paper_to_author(self):
      paper1 = create_paper(title='title1')
      user1 = create_random_default_user('user1')

      self.client.force_authenticate(user1)
      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": user1.id,
          "requestor":user1.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper1.id,
          "target_author_name": "author1",
        }
      )
      self.assertEqual(response.status_code, 201)
      
      paper2 = create_paper(title='title2')
      user2 = create_random_default_user('user2')

      self.client.force_authenticate(user2)
      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": user2.id,
          "requestor":user2.id,
          "provided_email":"user2@nowhere.org",
          "target_paper_id": paper2.id,
          "target_author_name": "author2",
        }
      )

      # User 1 can only see own claim
      self.client.force_authenticate(user1)
      response = self.client.get("/api/author_claim_case/")

      self.assertEqual(response.status_code, 200)
      self.assertEqual(len(response.data['results']), 1)
      data = response.data['results'][0]
      self.assertEqual(data['requestor']['id'], user1.id)

      # User 2 can only see own claim
      self.client.force_authenticate(user2)
      response = self.client.get("/api/author_claim_case/")

      self.assertEqual(response.status_code, 200)
      self.assertEqual(len(response.data['results']), 1)
      data = response.data['results'][0]
      self.assertEqual(data['requestor']['id'], user2.id)

    def test_claim_without_valid_paper_id_throws_error(self):
      claiming_user = create_random_default_user('claiming_user')
      self.client.force_authenticate(claiming_user)

      paper = create_paper(
        title='some title',
        uploaded_by=None,
      )

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user.id,
          "requestor":claiming_user.id,
          "provided_email":"example@example.com",
          "target_author_name": "some paper author",
        }
      )

      self.assertGreaterEqual(response.status_code, 400)

    def test_rejecting_claim_does_not_move_paper(self):
      moderator = create_moderator(first_name='moderator', last_name='moderator')
      claiming_user = create_random_default_user('claiming_user')
      self.client.force_authenticate(claiming_user)

      paper = create_paper(
        title='some title',
        uploaded_by=None,
      )

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user.id,
          "requestor":claiming_user.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper.id,
          "target_author_name": "some paper author",
        }
      )

      # Update Claim status
      claim = AuthorClaimCase.objects.get(id=response.data['id'])
      claim.status = 'OPEN'
      claim.save()

      # Deny claim
      self.client.force_authenticate(moderator)
      update_response = self.client.post(
        "/api/author_claim_case/moderator/", {
          "case_id": response.data['id'],
          "notify_user": True,
          "update_status": 'DENIED',
        }
      )

      claim = AuthorClaimCase.objects.get(id=response.data['id'])
      self.assertEqual(claim.status, 'DENIED')

    def test_close_claim_does_not_require_paper_to_be_set(self):
      moderator = create_moderator(first_name='moderator', last_name='moderator')
      claiming_user = create_random_default_user('claiming_user')
      self.client.force_authenticate(claiming_user)

      paper = create_paper(
        title='some title',
        uploaded_by=None,
      )

      # Update Claim status
      claim = AuthorClaimCase.objects.create(
        case_type="PAPER_CLAIM",
        status="OPEN",
        creator=claiming_user,
        requestor=claiming_user,
        provided_email="example@example.com",
      )

      # Close claim
      self.client.force_authenticate(moderator)
      response = self.client.post(
        "/api/author_claim_case/moderator/", {
          "case_id": claim.id,
          "notify_user": False,
          "update_status": 'DENIED',
        }
      )

      self.assertEqual(response.status_code, 200)

    def test_user_cannot_open_multiple_claims_for_same_paper(self):
      claiming_user1 = create_random_default_user('claiming_user')
      self.client.force_authenticate(claiming_user1)

      paper = create_paper(
        title='some title',
        uploaded_by=None,
      )

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user1.id,
          "requestor":claiming_user1.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper.id,
          "target_author_name": "random author",
        }
      )

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user1.id,
          "requestor":claiming_user1.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper.id,
          "target_author_name": "random author",
        }
      )      

      self.assertEqual(response.status_code, 400)

    def test_different_users_can_open_multiple_claims_for_same_author(self):
      claiming_user1 = create_random_default_user('claiming_user')
      claiming_user2 = create_random_default_user('claiming_user')

      paper = create_paper(
        title='some title',
        uploaded_by=None,
      )

      self.client.force_authenticate(claiming_user1)
      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user1.id,
          "requestor":claiming_user1.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper.id,
          "target_author_name": "random author",
        }
      )

      self.client.force_authenticate(claiming_user2)
      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user2.id,
          "requestor":claiming_user2.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper.id,
          "target_author_name": "random author",
        }
      )      

      self.assertEqual(response.status_code, 201)

    def test_user_cannot_claim_paper_for_other_creator(self):
      claiming_user = create_random_default_user('claiming_user')
      other_user = create_random_default_user('other_user')
      paper = create_paper(
        title='title1',
      )

      self.client.force_authenticate(claiming_user)

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type": PAPER_CLAIM,
          "creator": other_user.id,
          "provided_email": "email1@researchhub.com",
          "requestor": claiming_user.id,
          "target_author_name": "author1",
          "target_paper_id": paper.id,
        }
      )

      self.assertEqual(response.status_code, 403)

    def test_user_cannot_claim_paper_for_other_requestor(self):
      claiming_user = create_random_default_user('claiming_user')
      other_user = create_random_default_user('other_user')
      paper = create_paper(
        title='title1',
      )

      self.client.force_authenticate(claiming_user)

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type": PAPER_CLAIM,
          "creator": claiming_user.id,
          "provided_email": "email1@researchhub.com",
          "requestor": other_user.id,
          "target_author_name": "author1",
          "target_paper_id": paper.id,
        }
      )

      self.assertEqual(response.status_code, 403)

def test_moderator_can_claim_paper_for_any_user(self):
    moderator_user = create_moderator('moderator_user')
    other_user = create_random_default_user('other_user')
    paper = create_paper(
      title='title1',
    )

    self.client.force_authenticate(moderator_user)

    response = self.client.post(
      "/api/author_claim_case/", {
        "case_type": PAPER_CLAIM,
        "creator": other_user.id,
        "provided_email": "email1@researchhub.com",
        "requestor": moderator_user.id,
        "target_author_name": "author1",
        "target_paper_id": paper.id,
      }
    )

    self.assertEqual(response.status_code, 201)

    def test_user_can_claim_multiple_papers(self):
      moderator = create_moderator(first_name='moderator', last_name='moderator')
      claiming_user = create_random_default_user('claiming_user')
      self.client.force_authenticate(claiming_user)

      paper1 = create_paper(
        title='some title',
        uploaded_by=None,
      )

      paper2 = create_paper(
        title='some title',
        uploaded_by=None,
      )

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user.id,
          "requestor":claiming_user.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper1.id,
          "target_author_name": "random author",
        }
      )
      # Update Claim status
      claim = AuthorClaimCase.objects.get(id=response.data['id'])
      claim.status = 'OPEN'
      claim.save()

      # Approve claim
      self.client.force_authenticate(moderator)
      update_response = self.client.post(
        "/api/author_claim_case/moderator/", {
          "case_id": response.data['id'],
          "notify_user": True,
          "update_status": 'APPROVED',
        }
      )

      self.assertEqual(update_response.status_code, 200)

      response = self.client.post(
        "/api/author_claim_case/", {
          "case_type":"PAPER_CLAIM",
          "creator": claiming_user.id,
          "requestor":claiming_user.id,
          "provided_email":"example@example.com",
          "target_paper_id": paper2.id,
          "target_author_name": "random author",
        }
      )

      self.assertEqual(response.status_code, 201)
