from django.test import TestCase

from discussion.tests.helpers import (
    create_thread,
    create_comment,
    create_reply
)
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


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

    def test_thread_users_to_notify_includes_paper_authors(self):
        user_1 = create_random_default_user('Amy')
        user_2 = create_random_default_user('Bamy')
        self.paper.authors.add(user_1.author_profile)
        self.paper.authors.add(user_2.author_profile)
        self.assertTrue(user_1 in self.thread.users_to_notify)
        self.assertTrue(user_2 in self.thread.users_to_notify)

    def test_thread_users_to_notify_exlcudes_non_author_creator(self):
        user = create_random_default_user('Non-author')
        thread = create_thread(paper=self.paper, created_by=user)
        self.assertFalse(user in thread.users_to_notify)

    def test_thread_users_to_notify_inlcudes_author_creator(self):
        user = create_random_default_user('Author-and-creator')
        self.paper.authors.add(user.author_profile)
        thread = create_thread(paper=self.paper, created_by=user)
        self.assertTrue(user in thread.users_to_notify)

    def test_thread_users_to_notify_exlcudes_unsubscribed(self):
        user = create_random_default_user('Camy')
        self.paper.authors.add(user.author_profile)
        user.emailrecipient.paper_subscription.unsubscribe()
        self.assertFalse(user in self.thread.users_to_notify)

    def test_thread_users_to_notify_exlcudes_threads_false(self):
        user = create_random_default_user('Damy')
        user.emailrecipient.paper_subscription.threads = False
        user.emailrecipient.paper_subscription.save()
        self.paper.authors.add(user.author_profile)
        self.assertFalse(user in self.thread.users_to_notify)

    def test_comment_users_to_notify_includes_thread_creator(self):
        user = create_random_default_user('Eamy')
        thread = create_thread(created_by=user)
        comment = create_comment(thread=thread)
        self.assertTrue(user in comment.users_to_notify)

    def test_comment_users_to_notify_exlcudes_comment_creator(self):
        user = create_random_default_user('Famy')
        comment = create_comment(thread=self.thread, created_by=user)
        self.assertFalse(user in comment.users_to_notify)

    def test_comment_users_to_notify_exlcudes_unsubscribed(self):
        user = create_random_default_user('Gamy')
        thread = create_thread(created_by=user)
        user.emailrecipient.thread_subscription.unsubscribe()
        comment = create_comment(thread=thread)
        self.assertFalse(user in comment.users_to_notify)

    def test_comment_users_to_notify_exlcudes_comments_false(self):
        user = create_random_default_user('Hamy')
        thread = create_thread(created_by=user)
        user.emailrecipient.thread_subscription.comments = False
        user.emailrecipient.thread_subscription.save()
        comment = create_comment(thread=thread)
        self.assertFalse(user in comment.users_to_notify)

    def test_reply_users_to_notify_includes_comment_creator(self):
        user = create_random_default_user('Iamy')
        comment = create_comment(created_by=user)
        reply = create_reply(parent=comment)
        self.assertTrue(user in reply.users_to_notify)

    def test_reply_users_to_notify_exlcudes_reply_creator(self):
        user = create_random_default_user('Jamy')
        reply = create_reply(created_by=user)
        self.assertFalse(user in reply.users_to_notify)

    def test_reply_users_to_notify_exlcudes_unsubscribed(self):
        user = create_random_default_user('Kamy')
        comment = create_comment(created_by=user)
        user.emailrecipient.comment_subscription.unsubscribe()
        reply = create_reply(parent=comment)
        self.assertFalse(user in reply.users_to_notify)

    def test_reply_users_to_notify_exlcudes_replies_false(self):
        user = create_random_default_user('Lamy')
        comment = create_comment(created_by=user)
        user.emailrecipient.comment_subscription.replies = False
        user.emailrecipient.comment_subscription.save()
        reply = create_reply(parent=comment)
        self.assertFalse(user in reply.users_to_notify)

    def test_reply_child_users_to_notify_includes_reply_parent_creator(self):
        user = create_random_default_user('Mamy')
        reply_parent = create_reply(created_by=user)
        reply_child = create_reply(parent=reply_parent)
        self.assertTrue(user in reply_child.users_to_notify)

    def test_reply_child_users_to_notify_excludes_reply_child_creator(self):
        user = create_random_default_user('Namy')
        reply_parent = create_reply()
        reply_child = create_reply(parent=reply_parent, created_by=user)
        self.assertFalse(user in reply_child.users_to_notify)

    def test_reply_child_users_to_notify_exlcudes_unsubscribed(self):
        user = create_random_default_user('Oamy')
        reply_parent = create_reply(created_by=user)
        user.emailrecipient.reply_subscription.unsubscribe()
        reply_child = create_reply(parent=reply_parent)
        self.assertFalse(user in reply_child.users_to_notify)

    def test_reply_child_users_to_notify_exlcudes_replies_false(self):
        user = create_random_default_user('Pamy')
        reply_parent = create_reply(created_by=user)
        user.emailrecipient.reply_subscription.replies = False
        user.emailrecipient.reply_subscription.save()
        reply_child = create_reply(parent=reply_parent)
        self.assertFalse(user in reply_child.users_to_notify)

    def test_creating_thread_notifies_paper_submitter(self):
        submitter = create_random_default_user('Submitter')
        commenter = create_random_default_user('Commenter')
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=commenter)
        self.assertTrue(submitter in thread.users_to_notify)

    def test_creating_comment_notifies_paper_submitter(self):
        submitter = create_random_default_user('Submitter')
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper)
        comment = create_comment(thread=thread)
        self.assertTrue(submitter in comment.users_to_notify)

    def test_creating_reply_notifies_paper_submitter(self):
        submitter = create_random_default_user('Submitter')
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper)
        comment = create_comment(thread=thread)
        reply = create_reply(parent=comment)
        self.assertTrue(submitter in reply.users_to_notify)

    def test_thread_creator_not_receive_notification_on_own_contribution(self):
        submitter = create_random_default_user('Submitter')
        commenter = create_random_default_user('Commenter')
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=commenter)
        self.assertFalse(commenter in thread.users_to_notify)

    def test_comment_creator_not_receive_notification_on_own_contribution(self):
        submitter = create_random_default_user('Submitter')
        thread_creator = create_random_default_user('ThreadCreator')
        comment_creator = create_random_default_user('Commenter')
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=thread_creator)
        comment = create_comment(thread=thread, created_by=comment_creator)
        self.assertFalse(comment_creator in comment.users_to_notify)

    def test_reply_creator_not_receive_notification_on_own_contribution(self):
        submitter = create_random_default_user('Submitter')
        thread_creator = create_random_default_user('ThreadCreator')
        comment_creator = create_random_default_user('Commenter')
        reply_creator = create_random_default_user('ReplyCreator')
        paper = create_paper(uploaded_by=submitter)
        thread = create_thread(paper=paper, created_by=thread_creator)
        comment = create_comment(thread=thread, created_by=comment_creator)
        reply = create_reply(parent=comment, created_by=reply_creator)
        self.assertFalse(reply_creator in reply.users_to_notify)

    def test_creating_thread_notifies_post_creator(self):
        self.assertTrue(True, False)

    def test_creating_comment_notifies_post_creator(self):
        self.assertTrue(True, False)

    def test_creating_reply_notifies_post_creator(self):
        self.assertTrue(True, False)

    def test_creating_thread_notifies_hypothesis_creator(self):
        self.assertTrue(True, False)

    def test_creating_comment_notifies_hypothesis_creator(self):
        self.assertTrue(True, False)

    def test_creating_reply_notifies_hypothesis_creator(self):
        self.assertTrue(True, False)
