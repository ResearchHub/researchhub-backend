from psycopg2.errors import UniqueViolation

from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase, tag
from django.core.files.uploadedfile import SimpleUploadedFile

from paper.tasks import handle_duplicate_doi
from paper.utils import (
    convert_journal_url_to_pdf_url,
    convert_pdf_url_to_journal_url
)
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


class JournalPdfTests(TestCase):
    journal_test_urls = [
        'https://arxiv.org/abs/2007.10529',
        'https://jpet.aspetjournals.org/content/368/1/59',
        'https://www.biorxiv.org/content/10.1101/2020.04.14.040808v1',
        'https://www.jneurosci.org/content/29/13/3974',
        'https://www.thelancet.com/journals/journal_id/article/PIIS2215-0366(20)30308-4/fulltext',
        'https://www.nature.com/articles/srep42765',
        'https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0198090',
        'https://www.pnas.org/content/102/4/1193',
        'https://advances.sciencemag.org/content/1/6/e1500251',
        'https://onlinelibrary.wiley.com/doi/full/10.1111/jvim.15646',
        'https://academic.oup.com/nar/article/46/W1/W180/5033528',
        'https://www.sciencedirect.com/science/article/abs/pii/S105381191832161X',
        'https://link.springer.com/article/10.1007/s11033-020-05249-1',
        'https://www.cell.com/current-biology/fulltext/S0960-9822(19)31258-8',
        'https://ieeexplore.ieee.org/document/8982960'
    ]

    pdf_test_urls = [
        'https://arxiv.org/pdf/2007.10529.pdf',
        'https://jpet.aspetjournals.org/content/jpet/368/1/59.full.pdf',
        'https://www.biorxiv.org/content/10.1101/2020.04.14.040808v1.full.pdf',
        'https://www.jneurosci.org/content/jneuro/29/13/3974.full.pdf',
        'https://www.thelancet.com/action/showPdf?pii=S2215-0366(20)30308-4',
        'https://www.nature.com/articles/srep42765.pdf',
        'https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0198090&type=printable',
        'https://www.pnas.org/content/pnas/102/4/1193.full.pdf',
        'https://advances.sciencemag.org/content/advances/1/6/e1500251.full.pdf',
        'https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/jvim.15646?download=true',
        'https://academic.oup.com/nar/article-pdf/46/W1/W180/25110691/gky509.pdf'
    ]

    def test_journal_to_pdf(self):
        for i, url in enumerate(self.journal_test_urls):
            pdf_url, exists = convert_journal_url_to_pdf_url(url)
            if exists:
                print(pdf_url)
                self.assertEquals(pdf_url, self.pdf_test_urls[i])

    def test_pdf_to_journal(self):
        for i, url in enumerate(self.pdf_test_urls):
            journal_url, exists = convert_pdf_url_to_journal_url(url)
            if exists:
                print(journal_url)
                self.assertEquals(journal_url, self.journal_test_urls[i])
