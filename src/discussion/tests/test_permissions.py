import random

from discussion.permissions import Vote as VotePermission
from discussion.tests.helpers import (
    build_comment_data,
    build_discussion_default_url,
    build_discussion_detail_url,
    build_reply_data,
    build_thread_form,
    create_comment,
    create_reply,
    create_thread
)
from discussion.tests.tests import (
    BaseIntegrationTestCase as DiscussionIntegrationTestCase
)
from paper.tests.helpers import create_paper
from user.models import Author
from user.tests.helpers import create_random_authenticated_user
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
        self.author = create_random_authenticated_user('author')
        self.moderator = create_random_authenticated_user('moderator')

        self.add_paper_author(Author.objects.get(user=self.author))
        self.add_paper_moderator(self.moderator)

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

    def test_author_can_endorse_thread(self):
        thread = create_thread(title='A', paper=self.paper)
        response = self.get_thread_endorsement_post_response(
            self.author,
            thread
        )
        self.assertContains(
            response,
            thread.id,
            status_code=201
        )

    def test_moderator_can_endorse_thread(self):
        thread = create_thread(title='M', paper=self.paper)
        response = self.get_thread_endorsement_post_response(
            self.moderator,
            thread
        )
        self.assertContains(
            response,
            thread.id,
            status_code=201
        )

    def test_can_NOT_endorse_thread_if_not_author_or_moderator(self):
        thread = create_thread(title='N', paper=self.paper)
        response = self.get_thread_endorsement_post_response(self.user, thread)
        self.assertEqual(response.status_code, 403)

    def test_author_can_endorse_comment(self):
        comment = create_comment(text='A', thread=self.thread)
        response = self.get_comment_endorsement_post_response(
            self.author,
            comment
        )
        self.assertContains(
            response,
            comment.id,
            status_code=201
        )

    def test_moderator_can_endorse_comment(self):
        comment = create_comment(text='M', thread=self.thread)
        response = self.get_comment_endorsement_post_response(
            self.moderator,
            comment
        )
        self.assertContains(
            response,
            comment.id,
            status_code=201
        )

    def test_can_NOT_endorse_comment_if_not_author_or_moderator(self):
        comment = create_comment(text='N', thread=self.thread)
        response = self.get_comment_endorsement_post_response(
            self.user,
            comment
        )
        self.assertEqual(response.status_code, 403)

    def test_author_can_endorse_reply(self):
        reply = create_reply(text='A', parent=self.comment)
        response = self.get_reply_endorsement_post_response(
            self.author,
            reply
        )
        self.assertContains(
            response,
            reply.id,
            status_code=201
        )

    def test_moderator_can_endorse_reply(self):
        reply = create_reply(text='M', parent=self.comment)
        response = self.get_reply_endorsement_post_response(
            self.moderator,
            reply
        )
        self.assertContains(
            response,
            reply.id,
            status_code=201
        )

    def test_can_NOT_endorse_reply_if_not_author_or_moderator(self):
        reply = create_reply(text='N', parent=self.comment)
        response = self.get_reply_endorsement_post_response(
            self.user,
            reply
        )
        self.assertEqual(response.status_code, 403)

    def test_can_flag_thread_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_thread_flag_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_flag_thread_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_thread_flag_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_flag_comment_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_comment_flag_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_flag_comment_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_comment_flag_post_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_flag_reply_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_reply_flag_post_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_flag_reply_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_reply_flag_post_response(user)
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

    def test_can_NOT_vote_on_created_content(self):
        text = VotePermission.message

        response = self.get_thread_upvote_post_response(self.user)
        self.assertContains(response, text, status_code=403)

        response = self.get_thread_downvote_post_response(self.user)
        self.assertContains(response, text, status_code=403)

        response = self.get_comment_upvote_post_response(self.user)
        self.assertContains(response, text, status_code=403)

        response = self.get_comment_downvote_post_response(self.user)
        self.assertContains(response, text, status_code=403)

        response = self.get_reply_upvote_post_response(self.user)
        self.assertContains(response, text, status_code=403)

        response = self.get_reply_downvote_post_response(self.user)
        self.assertContains(response, text, status_code=403)

    def add_paper_author(self, author):
        self.paper.authors.add(author)
        self.paper.save()

    def add_paper_moderator(self, moderator):
        self.paper.moderators.add(moderator)
        self.paper.save()

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

    def get_thread_endorsement_post_response(self, user, thread):
        url = self.get_thread_endorsement_url(thread)
        response = self.get_endorsement_response(user, url)
        return response

    def get_thread_endorsement_url(self, thread):
        return self.base_url + f'paper/{self.paper.id}/discussion/{thread.id}/'

    def get_thread_flag_post_response(self, user):
        url = build_discussion_detail_url(self, 'thread')
        reason = 'This thread is inappropriate'
        response = self.get_flag_response(user, url, reason)
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

    def get_comment_endorsement_post_response(self, user, comment):
        url = self.get_comment_endorsement_url(comment)
        response = self.get_endorsement_response(user, url)
        return response

    def get_comment_endorsement_url(self, comment):
        return self.base_url + (
            f'paper/{self.paper.id}/discussion/{self.thread.id}/'
            + f'comment/{comment.id}/'
        )

    def get_comment_flag_post_response(self, user):
        url = build_discussion_detail_url(self, 'comment')
        reason = 'This comment is inappropriate'
        response = self.get_flag_response(user, url, reason)
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

    def get_reply_endorsement_post_response(self, user, reply):
        url = self.get_reply_endorsement_url(reply)
        response = self.get_endorsement_response(user, url)
        return response

    def get_reply_endorsement_url(self, reply):
        return self.base_url + (
            f'paper/{self.paper.id}/discussion/{self.thread.id}/'
            + f'comment/{self.comment.id}/reply/{reply.id}/'
        )

    def get_reply_flag_post_response(self, user):
        url = build_discussion_detail_url(self, 'reply')
        reason = 'This reply is inappropriate'
        response = self.get_flag_response(user, url, reason)
        return response

    def get_reply_upvote_post_response(self, user):
        url = build_discussion_detail_url(self, 'reply')
        response = self.get_upvote_response(user, url)
        return response

    def get_reply_downvote_post_response(self, user):
        url = build_discussion_detail_url(self, 'reply')
        response = self.get_downvote_response(user, url)
        return response

    def get_endorsement_response(self, user, url):
        url += 'endorse/'
        data = None
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_flag_response(self, user, url, reason):
        url += 'flag/'
        data = {
            'reason': reason
        }
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
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
