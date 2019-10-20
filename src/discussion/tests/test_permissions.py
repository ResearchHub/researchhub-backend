import random

from .helpers import (
    build_comment_data,
    build_discussion_default_url,
    build_discussion_detail_url,
    build_reply_data,
    build_thread_form,
    create_comment,
    create_reply,
    create_thread
)
from .tests import (
    BaseIntegrationTestCase as DiscussionIntegrationTestCase
)
from user.tests.helpers import create_random_authenticated_user
from paper.tests.helpers import create_paper
from utils.test_helpers import (
    get_authenticated_get_response,
    get_authenticated_post_response
)


class DiscussionThreadPermissionsIntegrationTests(
    DiscussionIntegrationTestCase
):

    def setUp(self):
        SEED = 'discussion'
        self.random_generator = random.Random(SEED)
        self.base_url = '/api/'
        self.user = create_random_authenticated_user('discussion_permissions')
        self.paper = create_paper(uploaded_by=self.user)
        self.thread = create_thread(paper=self.paper, created_by=self.user)
        self.comment = create_comment(thread=self.thread, created_by=self.user)
        self.reply = create_reply(parent=self.comment, created_by=self.user)
        self.trouble_maker = create_random_authenticated_user('trouble_maker')

    def test_all_users_can_view_threads(self):
        user = self.create_user_with_reputation(0)
        response = self.get_discussion_response(user)
        status_code = response.status_code
        self.assertEqual(status_code, 200)

    def test_can_post_thread_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_thread_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_post_thread_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_thread_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_post_comment_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_comment_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_post_comment_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_comment_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_post_reply_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_reply_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_post_reply_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_reply_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_upvote_thread_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_thread_upvote_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_upvote_thread_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_thread_upvote_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_downvote_thread_with_minimum_reputation(self):
        user = self.create_user_with_reputation(25)
        response = self.get_thread_downvote_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_downvote_thread_below_minimum_reputation(self):
        user = self.create_user_with_reputation(24)
        response = self.get_thread_downvote_post_response(user)
        import pdb; pdb.set_trace()
        self.assertEqual(response.status_code, 403)

    def test_can_upvote_comment_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_comment_upvote_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_upvote_comment_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_comment_upvote_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_downvote_comment_with_minimum_reputation(self):
        user = self.create_user_with_reputation(25)
        response = self.get_comment_downvote_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_downvote_comment_below_minimum_reputation(self):
        user = self.create_user_with_reputation(24)
        response = self.get_comment_downvote_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_upvote_reply_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_reply_upvote_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_upvote_reply_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_reply_upvote_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_downvote_reply_with_minimum_reputation(self):
        user = self.create_user_with_reputation(25)
        response = self.get_reply_downvote_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_downvote_reply_below_minimum_reputation(self):
        user = self.create_user_with_reputation(24)
        response = self.get_reply_downvote_post_response(user)
        self.assertEqual(response.status_code, 403)

    def create_user_with_reputation(self, reputation):
        unique_value = self.random_generator.random()
        user = self.create_random_authenticated_user(unique_value)
        user.reputation = reputation
        user.save()
        return user

    def get_discussion_response(self, user):
        url = build_discussion_default_url(self, 'thread')
        response = get_authenticated_get_response(
            user,
            url,
            content_type='application/json'
        )
        return response

    def get_thread_post_response(self, user):
        url = build_discussion_default_url(self, 'thread')
        form_data = build_thread_form(
            self.paper.id,
            'Permission Thread',
            'test permissions thread'
        )
        response = get_authenticated_post_response(
            user,
            url,
            form_data,
            content_type='multipart/form-data'
        )
        return response

    def get_thread_upvote_post_response(self, user):
        url = build_discussion_detail_url(self, 'thread')
        response = self.get_upvote_response(user, url)
        return response

    def get_thread_downvote_post_response(self, user):
        url = build_discussion_detail_url(self, 'thread')
        response = self.get_downvote_response(user, url)
        return response

    def get_comment_post_response(self, user):
        url = build_discussion_default_url(self, 'comment')
        data = build_comment_data(self.thread.id, 'test permissions comment')
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_comment_upvote_post_response(self, user):
        url = build_discussion_detail_url(self, 'comment')
        response = self.get_upvote_response(user, url)
        return response

    def get_comment_downvote_post_response(self, user):
        url = build_discussion_detail_url(self, 'comment')
        response = self.get_downvote_response(user, url)
        return response

    def get_reply_post_response(self, user):
        url = build_discussion_default_url(self, 'reply')
        data = build_reply_data(self.comment.id, 'test permissions reply')
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_reply_upvote_post_response(self, user):
        url = build_discussion_detail_url(self, 'reply')
        response = self.get_upvote_response(user, url)
        return response

    def get_reply_downvote_post_response(self, user):
        url = build_discussion_detail_url(self, 'reply')
        response = self.get_downvote_response(user, url)
        return response

    def get_upvote_response(self, user, url):
        url += 'upvote/'
        data = {}
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_downvote_response(self, user, url):
        url += 'downvote/'
        data = {}
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response
