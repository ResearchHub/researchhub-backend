from researchhub.celery import app
from researchhub.settings import (
    SOCIALACCOUNT_PROVIDERS,
    APP_ENV,
    PRODUCTION
)
from user.models import Author
from utils import sentry
from utils.exceptions import OrcidApiError
from utils.http import http_request, GET, POST

orcid = SOCIALACCOUNT_PROVIDERS['orcid']


class OrcidApi:
    def __init__(
        self,
        base_domain=orcid['BASE_DOMAIN'],
        access_token=orcid['ACCESS_TOKEN'],
        refresh_token=orcid['REFRESH_TOKEN'],
    ):
        self.base_url = f'https://pub.{base_domain}/v3.0'
        self.search_url = self.base_url + '/search'
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._build_default_headers()

    def _build_default_headers(self):
        self.headers = {
            'accept': 'application/json',
            'authorization': f'Bearer {self.access_token}'
        }

    def refetch_api_tokens(self, scope='/read-public'):
        data = {
            'client_id': orcid['CLIENT_ID'],
            'client_secret': orcid['CLIENT_SECRET'],
            'grant_type': 'client_credentials',
            'scope': scope,
        }
        response = http_request(POST, data)
        self.access_token = response.data['access_token']
        self.refresh_token = response.data['refresh_token']
        self._build_default_headers()

    def search_by_name(self, given_names, family_name):
        url = self.search_url + f'/?q="{given_names}%20{family_name}"'
        response = http_request(GET, url, headers=self.headers, timeout=2)
        return response

    def search_by_id(self, uid):
        url = self.base_url + f'/{uid}/record'
        response = http_request(GET, url, headers=self.headers, timeout=5)
        return response

    def search_by_paper_id(self, doi=None, arxiv=None):
        key = ''
        uid = ''
        if doi is not None:
            key = 'doi-self'
            uid = doi
        elif arxiv is not None:
            key = 'arxiv'
            uid = arxiv
        url = self.search_url + f'/?q={key}:{uid}'
        response = http_request(GET, url, headers=self.headers, timeout=5)
        return response, uid

    def get_authors(self, use_celery=PRODUCTION, **kwargs):
        response, uid = self.search_by_paper_id(**kwargs)
        try:
            response.raise_for_status()
            authors = []
            results = response.json()['result']
            if results is None:
                raise ValueError('Results was None')
            for result in results:
                self._attempt_to_add_author(
                    result,
                    authors,
                    use_celery=use_celery
                )
            return authors
        except Exception as e:
            error = OrcidApiError(e, 'Failed to get authors')
            print(error)
            return []

    def _attempt_to_add_author(
        self,
        result,
        authors,
        attempts=2,
        use_celery=True
    ):
        if use_celery:
            celery_add_author.apply_async(
                (result, authors, attempts),
                priority=4,
                countdown=5
            )
        else:
            celery_add_author(result, authors, attempts)
        return authors

    def get_record_as_author(self, record):
        author = record.json()
        orcid_id = author['orcid-identifier']['path']
        name = author['person']['name']
        first_name = name['given-names']['value']
        last_name = name['family-name']['value']
        return self.get_or_create_orcid_author(orcid_id, first_name, last_name)

    def get_or_create_orcid_author(self, orcid_id, first_name, last_name):
        author, created = Author.objects.get_or_create(
            orcid_id=orcid_id,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
            }
        )
        return author


orcid_api = OrcidApi()


@app.task(queue=f'{APP_ENV}_autopull_queue', ignore_result=False)
def celery_add_author(result, authors, attempts=2):
    tries = attempts
    while tries > 0:
        try:
            result_orcid_id = result['orcid-identifier']['path']
            record_response = orcid_api.search_by_id(result_orcid_id)
            author = orcid_api.get_record_as_author(record_response)
            authors.append(author)
        except Exception as e:
            print(e)
        tries -= 1
    return len(authors)
