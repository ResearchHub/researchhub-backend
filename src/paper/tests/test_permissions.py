import random

from django.test import TestCase, tag
from django.core.files.uploadedfile import SimpleUploadedFile

from .helpers import create_paper
from user.models import Author
from utils.test_helpers import (
    get_authenticated_patch_response,
    get_authenticated_post_response,
    get_authenticated_put_response,
    IntegrationTestHelper,
    TestHelper
)


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


class PaperPermissionsIntegrationTests(
    TestCase,
    BaseIntegrationMixin
):

    def setUp(self):
        SEED = 'paper'
        self.random_generator = random.Random(SEED)
        self.base_url = '/api/paper/'
        self.paper = create_paper()
        self.flag_reason = 'Inappropriate'

    @tag('aws')
    def test_can_post_paper_with_minimum_reputation(self):
        reputation = 1
        self.assertPostWithReputationResponds(reputation, 201)

    def test_can_NOT_post_paper_below_minimum_reputation(self):
        reputation = -1
        self.assertPostWithReputationResponds(reputation, 403)

    def test_can_flag_paper_with_minimum_reputation(self):
        user = self.create_user_with_reputation(50)
        response = self.get_flag_response(user)
        self.assertContains(response, self.flag_reason, status_code=201)

    def test_can_NOT_flag_paper_below_minimum_reputation(self):
        user = self.create_user_with_reputation(49)
        response = self.get_flag_response(user)
        self.assertEqual(response.status_code, 403)

    @tag('aws')
    def test_author_can_update_paper(self):
        user = self.create_random_authenticated_user('author')
        author = Author.objects.get(user=user)
        paper = self.create_paper_with_authors([author.id])

        response = self.get_patch_response(user, paper)
        self.assertEqual(response.status_code, 200)

        response = self.get_put_response(user, paper)
        self.assertEqual(response.status_code, 200)

    @tag('aws')
    def test_moderator_can_update_paper(self):
        moderator = self.create_random_authenticated_user('moderator')
        paper = self.create_paper_with_moderators([moderator.id])

        response = self.get_patch_response(moderator, paper)
        self.assertEqual(response.status_code, 200)

        response = self.get_put_response(moderator, paper)
        self.assertEqual(response.status_code, 200)

    def test_can_update_paper_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_patch_response(user, self.paper)
        self.assertEqual(response.status_code, 200)

    def test_can_NOT_update_paper_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_patch_response(user, self.paper)
        self.assertEqual(response.status_code, 403)

    def test_can_upvote_paper_with_minimum_reputation(self):
        user = self.create_user_with_reputation(1)
        response = self.get_upvote_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_upvote_paper_below_minimum_reputation(self):
        user = self.create_user_with_reputation(0)
        response = self.get_upvote_response(user)
        self.assertEqual(response.status_code, 403)

    def test_can_downvote_paper_with_minimum_reputation(self):
        user = self.create_user_with_reputation(25)
        response = self.get_downvote_response(user)
        self.assertEqual(response.status_code, 201)

    def test_can_NOT_downvote_paper_below_minimum_reputation(self):
        user = self.create_user_with_reputation(24)
        response = self.get_downvote_response(user)
        self.assertEqual(response.status_code, 403)

    def test_author_can_assign_moderator(self):
        author = self.create_random_authenticated_user('author1')
        paper = self.create_paper_with_authors([author.id])
        response = self.get_assign_moderator_response(author, paper)
        self.assertEqual(response.status_code, 200)

    def test_moderator_can_NOT_assign_moderator(self):
        moderator = self.create_random_authenticated_user('moderator1')
        paper = self.create_paper_with_moderators([moderator.id])
        response = self.get_assign_moderator_response(moderator, paper)
        self.assertEqual(response.status_code, 403)

    def test_uploader_can_NOT_assign_moderator(self):
        uploader = self.create_random_authenticated_user('uploader1')
        paper = create_paper(uploaded_by=uploader)
        response = self.get_assign_moderator_response(uploader, paper)
        self.assertEqual(response.status_code, 403)

    def test_can_NOT_assign_moderator_unless_author(self):
        random_user = self.create_random_authenticated_user('random1')
        paper = create_paper(title='Title For Test Can Not Assign Moderator')
        response = self.get_assign_moderator_response(random_user, paper)
        self.assertEqual(response.status_code, 403)

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

    def get_patch_response(self, user, paper):
        if paper is None:
            paper = self.paper
        url = self.base_url + f'{paper.id}/'
        data = {'title': 'Patched Paper Title'}
        response = get_authenticated_patch_response(
            user,
            url,
            data,
            content_type='multipart/form-data'
        )
        return response

    def get_put_response(self, user, paper):
        if paper is None:
            paper = self.paper
        url = self.base_url + f'{paper.id}/'
        form_data = self.build_paper_form()
        response = get_authenticated_put_response(
            user,
            url,
            form_data,
            content_type='multipart/form-data'
        )
        return response

    def get_assign_moderator_response(self, user, paper):
        url = self.base_url + f'{paper.id}/assign_moderator/'
        random_user = self.create_random_authenticated_user('random')
        data = {'moderators': random_user.id}
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
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

    def create_paper_with_authors(self, author_ids):
        paper = create_paper(title='Authored Paper')
        paper.authors.add(*author_ids)
        paper.save()
        return paper

    def create_paper_with_moderators(self, moderator_ids):
        paper = create_paper(title='Moderated Paper')
        paper.moderators.add(*moderator_ids)
        paper.save()
        return paper

    def get_flag_response(self, user):
        url = self.base_url + f'{self.paper.id}/flag/'
        data = {'reason': self.flag_reason}
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_upvote_response(self, user):
        url = self.base_url + f'{self.paper.id}/upvote/'
        data = {}
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response

    def get_downvote_response(self, user):
        url = self.base_url + f'{self.paper.id}/downvote/'
        data = {}
        response = get_authenticated_post_response(
            user,
            url,
            data,
            content_type='application/json'
        )
        return response
