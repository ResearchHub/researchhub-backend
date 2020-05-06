import base64
import json

import smart_open

from .exceptions import ElasticsearchPluginError
from paper.models import Paper
from researchhub.settings import ELASTICSEARCH_DSL
from utils.aws import http_to_s3
from utils.http import http_request, RequestMethods as methods
import utils.sentry as sentry


class IngestPdfPipeline:
    def __init__(self, index):
        self.host = ELASTICSEARCH_DSL.get('default').get('hosts')
        if type(self.host) is list:
            self.host = self.host[0]['host']
        self.url = self.host + f'/_ingest/pipeline/pdf'
        self._build_pipeline_if_not_exists()
        self.index = index

    def attach_all(self):
        """Encodes all paper files and adds them to Elasticsearch.

        Loops through all papers regardless of failures.
        """
        for paper in Paper.objects.all():
            self.attach_paper_pdf(paper)

    def attach_paper_pdf_by_id(self, paper_id):
        """Encodes the paper file and adds it to Elasticsearch.

        Arguments:
            paper_id (int) -- id of Paper object to get and add the pdf

        Return:
            response (requests.Response) -- result of attachment put request

        """
        paper = None
        try:
            paper = Paper.objects.get(pk=paper_id)
        except Paper.DoesNotExist as e:
            print(ElasticsearchPluginError(e))
            return
        return self.attach_paper_pdf(paper)

    def attach_paper_pdf(self, paper):
        """Encodes the `paper` file and adds it to Elasticsearch.

        Arguments:
            paper (obj) -- Paper object to get and add the pdf

        Return:
            response (requests.Response) -- result of attachment put request

        """
        url = self.host + f'/{self.index}/_doc/{paper.id}?pipeline=pdf'
        pdf = self.encode_file(paper.file.url)
        data = {
            'filename': paper.file.name,
            'pdf': pdf.decode('utf-8')
        }
        headers = {'Content-Type': 'application/json'}
        return self._send_put_request(
            url,
            data,
            headers,
            'Failed to index pdf'
        )

    def delete(self):
        """Deletes the pipeline from Elasticsearch"""
        return http_request(methods.DELETE, self.url)

    def encode_file(self, url):
        if '.s3.' in url:
            url = http_to_s3(url, with_credentials=True)
        with smart_open.open(url, 'rb') as f:
            return base64.b64encode(f.read())

    def _build_pipeline_if_not_exists(self):
        try:
            if self._check_pipeline_exists() is False:
                self._build_pipeline()
        except Exception as e:
            sentry.log_error(
                e,
                'Failed to build pipeline'
            )

    def _check_pipeline_exists(self):
        response = http_request(methods.GET, self.url)
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise ElasticsearchPluginError(
            None,
            f'Check pipeline failed with status code {response.status_code}'
        )

    def _build_pipeline(self):
        description = 'Extract pdf attachment'
        processors = [{'attachment': {'field': 'pdf'}}]
        data = {'description': description, 'processors': processors}
        headers = {'Content-Type': 'application/json'}
        self._send_put_request(
            self.url,
            data,
            headers,
            'Failed to add attachment to pipeline'
        )

    def _send_put_request(self, url, data, headers, error_message):
        """Returns the response of a put request to Elasticsearch.

        Raises ElasticsearchPluginError on error.
        """
        try:
            response = http_request(
                methods.PUT,
                url,
                json.dumps(data),
                timeout=8,
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
            return response
        except Exception as e:
            raise ElasticsearchPluginError(e, error_message)


pdf_pipeline = IngestPdfPipeline('paper')
