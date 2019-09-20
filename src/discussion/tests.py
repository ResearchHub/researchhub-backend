from django.test import TestCase
from django.contrib.sites.models import Site

from .models import Thread, Comment, Reply
from utils.test_helpers import IntegrationTestHelper, TestHelper


class BaseTestCase(TestCase, TestHelper):
    site = Site.objects.get_current()

    thread_title = 'Thread Title'
    thread_text = 'This is a thread.'
    comment_text = 'This is a comment.'
    reply_text = 'This is a reply.'

    def create_default_reply(self):
        comment = self.create_default_comment()
        user = self.create_random_default_user('reply')
        text = self.reply_text
        reply = self.create_reply(comment, user, text)
        return reply

    def create_reply(self, parent, user, text):
        reply = Reply.objects.create(
            parent=parent,
            created_by=user,
            text=text
        )
        return reply

    def create_default_comment(self):
        thread = self.create_default_thread()
        user = self.create_random_default_user('comment')
        text = self.comment_text
        comment = self.create_comment(thread, user, text)
        return comment

    def create_comment(self, thread, user, text):
        comment = Comment.objects.create(
            parent=thread,
            created_by=user,
            text=text
        )
        return comment

    def create_default_thread(self):
        paper = self.create_paper_without_authors()
        user = self.create_random_default_user('thread')
        title = self.thread_title
        text = self.thread_text
        thread = self.create_thread(paper, user, title, text)
        return thread

    def create_thread(self, paper, user, title, text):
        thread = Thread.objects.create(
            paper=paper,
            created_by=user,
            title=title,
            text=text
        )
        return thread


class ThreadTests(BaseTestCase):

    def test_string_representation(self):
        thread = self.create_default_thread()
        self.assertEqual(
            str(thread),
            'threadtestuser@gmail.com: Thread Title'
        )


class ReplyTests(BaseTestCase):

    def test_reply_to_reply(self):
        user = self.create_user()
        reply = self.create_default_reply()
        text = self.reply_text + ' 2'
        reply2 = self.create_reply(
            reply,
            user,
            text
        )
        self.assertEqual(reply2.parent, reply)

# class ThreadIntegrationTests(BaseTestCase, IntegrationTestHelper):

#     def test_create_thread(self):
#         paper = self.create_paper_without_authors()
#         response = self.add_thread_to(paper.id)
#         self.assertEqual(response.status_code, 200)

#     def add_thread_to(self, paper_id):
#         url = f'/api/paper/{paper_id}/discussion/'
#         body = {
#             "title": "hello",
#         }
#         client = self.get_default_authenticated_client()
#         response = self.post_response(url, body, client=client)
#         return response
