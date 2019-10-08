import random
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from discussion.tests.tests import (
    BaseIntegrationTestCase as DiscussionIntegrationTestCase
)
from utils.test_helpers import (
    get_authenticated_post_response,
    IntegrationTestHelper,
    TestHelper
)

# REFACTOR: These probably should just be tested in the applications pertaining
# to them to avoid code duplication and inheritance issues.


class BaseIntegrationMixin(
    TestHelper,
    IntegrationTestHelper
):

    def assertPostWithReputationResponds(self, reputation, status_code):
        response = self.post_with_reputation(reputation)
        self.assertEqual(response.status_code, status_code)

    def post_with_reputation(self):
        raise NotImplementedError

    def create_user_with_reputation(self, reputation):
        unique_value = self.random_generator.random()
        user = self.create_random_authenticated_user(unique_value)
        user.reputation = reputation
        user.save()
        return user


class DiscussionThreadPermissionsIntegrationTests(
    DiscussionIntegrationTestCase,
    BaseIntegrationMixin
):

    def setUp(self):
        SEED = 'discussion'
        self.random_generator = random.Random(SEED)

    def test_all_users_can_view_threads(self):
        user = self.create_user_with_reputation(0)
        response = self.get_discussion_response(user)
        status_code = response.status_code
        self.assertEqual(status_code, 200)

    def test_can_post_thread_with_minimum_reputation(self):
        reputation = 1
        self.assertPostWithReputationResponds(reputation, 201)

    def test_can_NOT_post_thread_below_minimum_reputation(self):
        reputation = 0
        self.assertPostWithReputationResponds(reputation, 403)

    def post_with_reputation(self, reputation):
        user = self.create_user_with_reputation(reputation)
        response = self.get_thread_submission_response(user)
        return response

    def get_discussion_response(self, user):
        thread_data = self.post_default_thread()
        url = self.build_discussion_url(thread_data)
        response = self.get_authenticated_get_response(
            user,
            url,
            content_type='application/json'
        )
        return response

    def get_thread_submission_response(self, user):
        paper = self.create_paper_without_authors()
        paper_id = paper.id
        url = self.base_url + f'{paper_id}/discussion/'
        form_data = self.build_default_thread_form(paper_id)
        response = get_authenticated_post_response(
            user,
            url,
            form_data,
            content_type='multipart/form-data'
        )
        return response


class PaperPermissionsIntegrationTests(
    TestCase,
    BaseIntegrationMixin
):

    def setUp(self):
        SEED = 'paper'
        self.random_generator = random.Random(SEED)
        self.base_url = '/api/paper/'

    def test_can_post_paper_with_minimum_reputation(self):
        reputation = 1
        self.assertPostWithReputationResponds(reputation, 201)

    def test_can_NOT_post_paper_below_minimum_reputation(self):
        reputation = -1
        self.assertPostWithReputationResponds(reputation, 403)

    def post_with_reputation(self, reputation):
        user = self.create_user_with_reputation(reputation)
        response = self.get_paper_submission_response(user)
        return response

    def get_paper_submission_response(self, user):
        url = self.base_url
        form_data = self.build_paper_form()
        response = get_authenticated_post_response(
            user,
            url,
            form_data,
            content_type='multipart/form-data'
        )
        return response

    def build_paper_form(self):
        file = SimpleUploadedFile('../config/paper.pdf', b'file_content')
        hub = self.create_hub('Cryptography')
        university = self.create_university(name='Univeristy of Atlanta')
        author = self.create_author_without_user(
            university,
            first_name='Tom',
            last_name='Riddle'
        )
        form = {
            'title': 'The Best Paper',
            'paper_publish_date': self.paper_publish_date,
            'file': file,
            'hubs': [hub.id],
            'authors': [1, author.id]
        }
        return form
