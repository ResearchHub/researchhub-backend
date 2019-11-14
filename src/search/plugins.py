import base64
import requests
import json

from django.core.exceptions import ImproperlyConfigured
from smart_open import open

from .exceptions import ElasticsearchPluginError
from paper.models import Paper
from researchhub.settings import ELASTICSEARCH_DSL
import utils.sentry as sentry


class IngestPdfProcessor(object):
    def __init__(self):
        self.es_host = ELASTICSEARCH_DSL.get('default').get('hosts')
        self.pipeline_url = self.es_host + f'/_ingest/pipeline/pdf'

    def attach(self, document):
        self.document = document
        self._get_document_index()
        self._create_pipeline_if_not_exists()
        for paper in Paper.objects.all():
            self._index_pdf(paper)

    def encode_file(self, url):
        with open(url, 'rb') as f:
            # f.seek(0)
            return base64.b64encode(f.read())

    def _get_document_index(self):
        index_meta = getattr(self.document, 'Index')

        if not index_meta:
            message = (
                f'You must declare the Index class inside '
                f'{self.document.__name__}'
            )
            raise ElasticsearchPluginError(ImproperlyConfigured, message)

        self.index = index_meta.name

    def _create_pipeline_if_not_exists(self):
        if self._check_pipeline_exists() is False:
            self._create_pipeline()

    def _check_pipeline_exists(self):
        response = requests.get(self.pipeline_url)
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise ElasticsearchPluginError(
            None,
            f'Check pipeline failed with status code {response.status_code}'
        )

    def _create_pipeline(self):
        description = 'Extract pdf attachment'
        processors = [{'attachment': {'field': 'pdf'}}]
        data = {'description': description, 'processors': processors}
        headers = {'Content-Type': 'application/json'}
        self._send_put_request(
            self.pipeline_url,
            data,
            headers,
            'Failed to add attachment to pipeline'
        )

    def _index_pdf(self, paper):
        url = self.es_host + f'/{self.index}/_doc/{paper.id}?pipeline=pdf'
        pdf = self.encode_file(paper.file.url)
        data = {
            'filename': paper.file.name,
            'pdf': pdf.decode('utf-8')
        }
        headers = {'Content-Type': 'application/json'}
        self._send_put_request(url, data, headers, 'Failed to index pdf')

    def _send_put_request(self, url, data, headers, error_message):
        try:
            response = requests.put(
                url,
                json.dumps(data),
                headers=headers
            )
            if not response.ok:
                message = (
                    f'Request to Elasticsearch failed with'
                    f'{response.status_code}'
                )
                sentry.log_error(
                    response.text,
                    message
                )
        except Exception as e:
            raise ElasticsearchPluginError(e, error_message)


ingest_pdf_processor = IngestPdfProcessor()
