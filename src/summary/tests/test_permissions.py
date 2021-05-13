from django.test import TestCase

from .helpers import build_summary_data, create_summary
from paper.tests.helpers import create_paper
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_authenticated_user_with_reputation
)
from utils.test_helpers import (
    get_authenticated_delete_response,
    get_authenticated_patch_response,
    get_authenticated_post_response,
    get_authenticated_put_response
)


class SummaryPermissionsTests(TestCase):

    def setUp(self):
        self.base_url = '/api/summary/'
        self.user = create_random_authenticated_user('summary_user')
        self.paper = create_paper(title='Summary Permissions Tests')
        self.summary_text = 'This is a summary for the permissions tests'
        self.summary = create_summary(
            self.summary_text,
            self.user,
            self.paper.id
        )

    def test_can_propose_summary_edit_with_minimum_reputation(self):
        # TODO: Get reputation from json
        user = create_random_authenticated_user_with_reputation(1, 1)
        response = self.get_summary_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_propose_summary_edit_below_minimum_reputation(self):
        user = create_random_authenticated_user_with_reputation(0, 0)
        response = self.get_summary_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_propose_first_summary_if_user_is_uploader(self):
        uploader = create_random_authenticated_user_with_reputation(
            'uploader',
            0
        )
        paper = create_paper(
            title='Summary Paper With Uploader',
            uploaded_by=uploader
        )
        response = self.get_first_summary_post_response(
            uploader,
            paper_id=paper.id
        )
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_propose_first_summary_if_user_is_not_uploader(self):
        user = create_random_authenticated_user_with_reputation(
            'not_uploader',
            0
        )
        response = self.get_first_summary_post_response(
            user
        )
        self.assertEqual(response.status_code, 403)

    def test_can_patch_unapproved_summary_when_user_is_proposer(self):
        proposer = create_random_authenticated_user('patch_proposer')
        summary = create_summary('patch summary', proposer, self.paper.id)
        response = self.get_summary_patch_response(proposer, summary=summary)
        self.assertEqual(response.status_code, 200)

    def test_can_NOT_patch_unapproved_summary_when_not_proposer(self):
        user = create_random_authenticated_user('not_patch_proposer')
        response = self.get_summary_patch_response(user)
        self.assertEqual(response.status_code, 403)

    def test_uploader_can_patch_approved_summary_without_approver(self):
        user = create_random_authenticated_user('patch_uploader')
        paper = create_paper(uploaded_by=user)
        approver = None
        summary = self.create_approved_summary(
            user,
            approver,
            paper_id=paper.id
        )
        response = self.get_summary_patch_response(user, summary=summary)
        self.assertEqual(response.status_code, 200)

    def test_can_NOT_patch_approved_summary_without_approver(self):
        user = create_random_authenticated_user('fail_patch_uploader')
        approver = None
        summary = self.create_approved_summary(
            user,
            approver
        )
        response = self.get_summary_patch_response(user, summary=summary)
        self.assertEqual(response.status_code, 403)

    def test_can_NOT_patch_summary_if_approved_by_user(self):
        user = create_random_authenticated_user('fail_patch')
        paper = create_paper(uploaded_by=user)
        approver = self.user
        summary = self.create_approved_summary(
            user,
            approver,
            paper_id=paper.id
        )
        response = self.get_summary_patch_response(user, summary=summary)
        self.assertEqual(response.status_code, 403)

    def test_can_put_unapproved_summary_when_user_is_proposer(self):
        proposer = create_random_authenticated_user('put_proposer')
        summary = create_summary('put summary', proposer, self.paper.id)
        response = self.get_summary_put_response(proposer, summary=summary)
        self.assertEqual(response.status_code, 200)

    def test_can_NOT_put_unapproved_summary_when_not_proposer(self):
        user = create_random_authenticated_user('not_put_proposer')
        response = self.get_summary_put_response(user)
        self.assertEqual(response.status_code, 403)

    def test_uploader_can_put_approved_summary_without_approver(self):
        user = create_random_authenticated_user('put_uploader')
        paper = create_paper(uploaded_by=user)
        approver = None
        summary = self.create_approved_summary(
            user,
            approver,
            paper_id=paper.id
        )
        response = self.get_summary_put_response(user, summary=summary)
        self.assertEqual(response.status_code, 200)

    def test_can_NOT_put_approved_summary_without_approver(self):
        user = create_random_authenticated_user('fail_put_uploader')
        approver = None
        summary = self.create_approved_summary(
            user,
            approver
        )
        response = self.get_summary_put_response(user, summary=summary)
        self.assertEqual(response.status_code, 403)

    def test_can_NOT_put_summary_if_approved_by_user(self):
        user = create_random_authenticated_user('fail_put')
        paper = create_paper(uploaded_by=user)
        approver = self.user
        summary = self.create_approved_summary(
            user,
            approver,
            paper_id=paper.id
        )
        response = self.get_summary_put_response(user, summary=summary)
        self.assertEqual(response.status_code, 403)

    def test_can_delete_unapproved_summary_when_user_is_proposer(self):
        proposer = create_random_authenticated_user('delete_proposer')
        summary = create_summary('delete summary', proposer, self.paper.id)
        response = self.get_summary_delete_response(proposer, summary=summary)
        self.assertEqual(response.status_code, 204)

    def test_can_NOT_delete_unapproved_summary_when_not_proposer(self):
        user = create_random_authenticated_user('not_delete_proposer')
        response = self.get_summary_delete_response(user)
        self.assertEqual(response.status_code, 403)

    def test_uploader_can_delete_approved_summary_without_approver(self):
        user = create_random_authenticated_user('delete_uploader')
        paper = create_paper(uploaded_by=user)
        approver = None
        summary = self.create_approved_summary(
            user,
            approver,
            paper_id=paper.id
        )
        response = self.get_summary_delete_response(user, summary=summary)
        self.assertEqual(response.status_code, 204)

    def test_can_NOT_delete_approved_summary_without_approver(self):
        user = create_random_authenticated_user('fail_delete_uploader')
        approver = None
        summary = self.create_approved_summary(
            user,
            approver
        )
        response = self.get_summary_delete_response(user, summary=summary)
        self.assertEqual(response.status_code, 403)

    def test_can_NOT_delete_summary_if_approved_by_user(self):
        user = create_random_authenticated_user('fail_delete')
        paper = create_paper(uploaded_by=user)
        approver = self.user
        summary = self.create_approved_summary(
            user,
            approver,
            paper_id=paper.id
        )
        response = self.get_summary_delete_response(user, summary=summary)
        self.assertEqual(response.status_code, 403)

    def get_first_summary_post_response(self, user, paper_id=None):
        if paper_id is None:
            paper_id = self.paper.id
        url = self.base_url + 'first/'
        data = build_summary_data(self.summary_text, paper_id, None)
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_summary_post_response(self, user, paper_id=None):
        if paper_id is None:
            paper_id = self.paper.id
        url = self.base_url
        data = build_summary_data(self.summary_text, paper_id, None)
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_summary_patch_response(self, user, summary=None):
        if summary is None:
            summary = self.summary
        url = self.base_url + f'{summary.id}/'
        data = {'summary': 'A patch update'}
        response = get_authenticated_patch_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_summary_put_response(self, user, summary=None):
        if summary is None:
            summary = self.summary
        url = self.base_url + f'{summary.id}/'
        data = build_summary_data('A put update', self.paper.id, None)
        response = get_authenticated_put_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_summary_delete_response(self, user, summary=None):
        if summary is None:
            summary = self.summary
        url = self.base_url + f'{summary.id}/'
        data = None
        response = get_authenticated_delete_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def create_approved_summary(self, proposed_by, approved_by, paper_id=None):
        if paper_id is None:
            paper_id = self.paper.id
        summary = create_summary(self.summary_text, proposed_by, paper_id)
        summary.approve(approved_by)
        summary.save()
        return summary
