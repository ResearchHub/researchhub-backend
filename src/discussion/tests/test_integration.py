import random

from .helpers import create_thread
from .tests import BaseIntegrationTestCase
from utils.test_helpers import (
    get_authenticated_post_response,
    get_user_from_response,
)


class DiscussionIntegrationTests(BaseIntegrationTestCase):

    def setUp(self):
        SEED = 'discussion'
        self.random_generator = random.Random(SEED)

    def test_discussion_view_shows_threads(self):
        thread = self.create_default_thread()
        paper_id = thread.paper.id
        url = self.base_url + f'{paper_id}/discussion/'
        response = self.get_get_response(url)
        text = thread.title
        self.assertContains(response, text, status_code=200)

    def test_create_thread(self):
        user = self.create_user_with_reputation(1)
        response = self.get_thread_submission_response(user)
        text = self.thread_title
        self.assertContains(response, text, status_code=201)

    def test_thread_is_created_by_current_user(self):
        user = self.create_user_with_reputation(1)
        response = self.get_thread_submission_response(user)
        response_user = get_user_from_response(response)
        text = response_user.id
        self.assertContains(response, text, status_code=201)

    def test_comment_is_created_by_current_user(self):
        user = self.create_user_with_reputation(1)
        response = self.get_comment_post_response(user)
        response_user = get_user_from_response(response)
        text = response_user.id
        self.assertContains(response, text, status_code=201)

    def test_create_upvote_for_thread(self):
        thread = create_thread()
        user = self.create_user_with_reputation(1)
        response = self.get_upvote_response(user, thread)
        text = 'vote_type'
        self.assertContains(response, text, status_code=201)

    def create_user_with_reputation(self, reputation):
        unique_value = self.random_generator.random()
        user = self.create_random_authenticated_user(unique_value)
        user.reputation = reputation
        user.save()
        return user

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

    def get_comment_post_response(self, user):
        thread = self.create_default_thread()
        thread_id = thread.id

        paper_id = thread.paper.id

        url = self.base_url + f'{paper_id}/discussion/{thread_id}/comment/'

        form_data = self.build_default_comment_form(thread_id)

        response = get_authenticated_post_response(
            user,
            url,
            form_data,
            content_type='multipart/form-data'
        )
        return response

    def get_upvote_response(self, user, thread):
        url = self.base_url + (
            f'{thread.paper.id}/discussion/{thread.id}/upvote/'
        )

        data = {}

        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response
