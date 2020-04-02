from psycopg2.errors import UniqueViolation

from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase, tag
from django.core.files.uploadedfile import SimpleUploadedFile

from paper.tasks import handle_duplicate_doi
from utils.test_helpers import (
    IntegrationTestHelper,
    TestHelper,
    get_user_from_response
)


class PaperIntegrationTests(
    TestCase,
    TestHelper,
    IntegrationTestHelper
):
    base_url = '/api/paper/'

    def test_get_base_route(self):
        response = self.get_get_response(self.base_url)
        self.assertEqual(response.status_code, 200)

    @tag('aws')
    def test_upload_paper(self):
        response = self.submit_paper_form()
        text = 'The Simple Paper'
        self.assertContains(response, text, status_code=201)

    @tag('aws')
    def test_paper_uploaded_by_request_user(self):
        response = self.submit_paper_form()
        user = get_user_from_response(response)
        text = '"uploaded_by":{"id":%d' % user.id
        self.assertContains(response, text, status_code=201)

    def submit_paper_form(self):
        client = self.get_default_authenticated_client()
        url = self.base_url
        form_data = self.build_paper_form()
        response = client.post(url, form_data)
        return response

    def build_paper_form(self):
        file = SimpleUploadedFile('../config/paper.pdf', b'file_content')
        hub = self.create_hub('Film')
        hub_2 = self.create_hub('Comedy')
        university = self.create_university(name='Charleston')
        author = self.create_author_without_user(
            university,
            first_name='Donald',
            last_name='Duck'
        )

        form = {
            'title': 'The Simple Paper',
            'paper_publish_date': self.paper_publish_date,
            'file': file,
            'hubs': [hub.id, hub_2.id],
            'authors': [author.id],
        }
        return form


class DuplicatePaperIntegrationTest(
    TransactionTestCase,
    TestHelper,
    IntegrationTestHelper
):
    def create_original_paper(self, doi='1'):
        original_paper = self.create_paper_without_authors()
        original_paper.doi = doi
        original_paper.save()
        return original_paper

    def test_duplicate_papers(self):
        doi = '1.1.1'
        user1 = self.create_random_authenticated_user('user_1')
        user2 = self.create_random_authenticated_user('user_2')
        original_paper = self.create_original_paper(doi=doi)
        new_paper = self.create_paper_without_authors()

        # Adding upvote to papers
        self.create_upvote(user1, original_paper)
        self.create_upvote(user1, new_paper)
        self.create_upvote(user2, new_paper)

        # Adding threads to papers
        self.create_thread(user1, original_paper, text='thread_1')
        self.create_thread(user2, new_paper, text='thread_2')

        # Adding bullet point to papers
        self.create_bulletpoint(user1, original_paper, text='original_point')
        self.create_bulletpoint(user2, new_paper, text='new_point')

        try:
            new_paper.doi = doi
            new_paper.save()
        except (UniqueViolation, IntegrityError):
            handle_duplicate_doi(new_paper, doi)

        # Checking merging results
        original_results, new_results = 2, 0
        original_paper_votes = original_paper.votes.count()
        new_paper_votes = new_paper.votes.count()
        self.assertEqual(original_paper_votes, original_results)
        self.assertEqual(new_paper_votes, new_results)

        original_thread_results = set(['thread_1', 'thread_2'])
        original_paper_threads = original_paper.threads.count()
        original_paper_threads_text = set(original_paper.threads.values_list(
            'plain_text',
            flat=True
        ))
        new_paper_threads = new_paper.threads.count()
        self.assertEqual(original_paper_threads, original_results)
        self.assertEqual(new_paper_threads, new_results)
        self.assertEqual(original_paper_threads_text, original_thread_results)

        original_bulletpoint_results = set(['original_point', 'new_point'])
        original_paper_bulletpoints = original_paper.bullet_points.count()
        original_points_text = set(original_paper.bullet_points.values_list(
            'plain_text',
            flat=True
        ))
        new_paper_bulletpoints = new_paper.bullet_points.count()
        self.assertEqual(original_paper_bulletpoints, original_results)
        self.assertEqual(new_paper_bulletpoints, new_results)
        self.assertEqual(original_points_text, original_bulletpoint_results)

        new_paper_id = None
        self.assertEqual(new_paper.id, new_paper_id)
