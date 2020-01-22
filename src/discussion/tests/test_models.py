from django.test import TestCase

from discussion.tests.helpers import (
    create_thread,
    create_comment,
    create_reply
)
from paper.tests.helpers import create_paper


class DiscussionModelsTests(TestCase):

    def setUp(self):
        self.paper = create_paper()
        self.thread = create_thread(paper=self.paper)
        self.comment = create_comment(thread=self.thread)
        self.reply = create_reply(parent=self.comment)

    def test_thread_parent_is_paper(self):
        self.assertEqual(self.thread.parent, self.paper)

    def test_comment_paper_property(self):
        self.assertEqual(self.comment.paper, self.paper)

    def test_reply_paper_property(self):
        self.assertEqual(self.reply.paper, self.paper)
