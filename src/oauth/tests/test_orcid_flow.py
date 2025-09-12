import json
from base64 import b64decode, b64encode
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib.sites.models import Site
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from requests.exceptions import HTTPError
from rest_framework.authtoken.models import Token

from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.models import Author
from user.tests.helpers import create_random_authenticated_user

# python src/manage.py test oauth.tests.test_orcid_flow.OrcidIntegrationTests
TEST_ORCID_CONFIG = {
    "ORCID_CLIENT_ID": "test-client",
    "ORCID_CLIENT_SECRET": "test-secret",
    "ORCID_REDIRECT_URL": "http://testserver/orcid/callback",
    "ORCID_BASE_URL": "http://orcid.test",
    "ORCID_SCOPE": "/read-limited",
}

SAMPLE_ORCID_ID = "0000-0002-1825-0097"
VALID_ORCID_HEADERS = {"content-type": "application/vnd.orcid+json"}
INVALID_ORCID_HEADERS = {"content-type": "text/html"}
STANDARD_AUTHOR_DEFAULTS = {"first_name": "Test", "last_name": "User"}
HTTP_SUCCESS = 200
HTTP_REDIRECT = 302


@override_settings(**TEST_ORCID_CONFIG)
@patch("oauth.services.download_pdf")
@patch("oauth.services.process_openalex_works")
@patch("oauth.services.get_user_publication_dois")
@patch("oauth.tasks.sync_orcid_publications.delay")
@patch("oauth.orcid_views.exchange_orcid_code_for_tokens")
@patch("oauth.orcid_views.retryable_requests_session")
class OrcidIntegrationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = create_random_authenticated_user("test_user")
        self.auth_token = Token.objects.get(user=self.user)
        self.setup_test_site_for_django_tests()
        self.setup_orcid_api_endpoint_urls()

    def tearDown(self):
        self.cleanup_all_test_database_records()

    def setup_test_site_for_django_tests(self):
        Site.objects.get_or_create(
            id=1, defaults={"domain": "testserver", "name": "test"}
        )

    def setup_orcid_api_endpoint_urls(self):
        self.connect_endpoint = reverse("orcid_connect")
        self.check_endpoint = reverse("orcid_check")
        self.callback_endpoint = reverse("orcid_callback")
        self.sync_endpoint = reverse("orcid_sync")

    def setup_orcid_django_social_application(self):
        orcid_app, _ = SocialApp.objects.get_or_create(
            provider="orcid",
            defaults={
                "name": "ORCID",
                "client_id": TEST_ORCID_CONFIG["ORCID_CLIENT_ID"],
                "secret": TEST_ORCID_CONFIG["ORCID_CLIENT_SECRET"],
            },
        )
        orcid_app.sites.add(Site.objects.get_current())
        return orcid_app

    def setup_user_orcid_account_with_token(self, access_token="test-access-token"):
        orcid_app = self.setup_orcid_django_social_application()
        orcid_account, _ = SocialAccount.objects.get_or_create(
            user=self.user, provider="orcid", uid=SAMPLE_ORCID_ID
        )
        SocialToken.objects.get_or_create(
            app=orcid_app, account=orcid_account, defaults={"token": access_token}
        )
        return orcid_app, orcid_account

    def create_test_author(self, name_overrides=None):
        defaults = STANDARD_AUTHOR_DEFAULTS.copy()
        if name_overrides:
            defaults.update(name_overrides)
        return Author.objects.get_or_create(user=self.user, defaults=defaults)[0]

    def build_request_headers_with_user_token(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.auth_token.key}"}

    def encode_oauth_callback_state_data(self, return_url="http://testserver/page"):
        state_data = {"user_id": self.user.id, "return_to": return_url}
        return b64encode(json.dumps(state_data).encode()).decode()

    def mock_valid_orcid_response(self, mock_session):
        mock_response = Mock(status_code=HTTP_SUCCESS, headers=VALID_ORCID_HEADERS)
        mock_session.return_value.__enter__.return_value.get.return_value = (
            mock_response
        )

    def mock_invalid_orcid_response(self, mock_session):
        mock_response = Mock(status_code=HTTP_SUCCESS, headers=INVALID_ORCID_HEADERS)
        mock_session.return_value.__enter__.return_value.get.return_value = (
            mock_response
        )

    def assert_successful_response(self, response):
        self.assertEqual(response.status_code, HTTP_SUCCESS)

    def assert_redirect_response(self, response):
        self.assertEqual(response.status_code, HTTP_REDIRECT)

    def assert_orcid_success_redirect(self, response):
        self.assert_redirect_response(response)
        self.assertIn("orcid_sync=ok", response.url)
        self.assertIn(f"user_id={self.user.id}", response.url)

    def assert_orcid_failure_redirect(self, response):
        self.assert_redirect_response(response)
        self.assertIn("orcid_sync=fail", response.url)

    def cleanup_all_test_database_records(self):
        for model in [Authorship, SocialToken, SocialAccount, Author, Paper]:
            model.objects.all().delete()

        for attr in ["auth_token", "user"]:
            if hasattr(self, attr):
                getattr(self, attr).delete()

    def test_orcid_check_returns_disconnected_when_no_account_exists(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        response = self.client.post(
            self.check_endpoint,
            {},
            format="json",
            **self.build_request_headers_with_user_token(),
        )

        self.assert_successful_response(response)
        self.assertFalse(response.data["connected"])
        self.assertTrue(response.data["needs_reauth"])

    def test_orcid_check_returns_connected_when_token_is_valid(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        self.setup_user_orcid_account_with_token()
        self.mock_valid_orcid_response(mock_http_session)

        response = self.client.post(
            self.check_endpoint,
            {},
            format="json",
            **self.build_request_headers_with_user_token(),
        )

        self.assert_successful_response(response)
        self.assertTrue(response.data["connected"])
        self.assertFalse(response.data["needs_reauth"])

    def test_orcid_check_returns_disconnected_when_token_is_invalid(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        self.setup_user_orcid_account_with_token("expired-token")
        self.mock_invalid_orcid_response(mock_http_session)

        response = self.client.post(
            self.check_endpoint,
            {},
            format="json",
            **self.build_request_headers_with_user_token(),
        )

        self.assert_successful_response(response)
        self.assertFalse(response.data["connected"])
        self.assertTrue(response.data["needs_reauth"])

    def test_orcid_sync_triggers_background_task(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        self.setup_user_orcid_account_with_token()

        response = self.client.post(
            self.sync_endpoint,
            {},
            format="json",
            **self.build_request_headers_with_user_token(),
        )

        self.assert_successful_response(response)
        self.assertTrue(response.data.get("ok"))
        mock_sync_task.assert_called_once_with(self.user.id)

    def test_orcid_connect_generates_valid_authorization_url(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        response = self.client.post(
            self.connect_endpoint,
            {"return_to": "http://example.com/success"},
            format="json",
            **self.build_request_headers_with_user_token(),
        )

        self.assert_successful_response(response)
        self.assertIn("auth_url", response.data)
        self.assertEqual(response.data["user_id"], self.user.id)

        authorization_url = response.data["auth_url"]
        self.assertIn("orcid.test/oauth/authorize", authorization_url)
        self.assertIn("state=", authorization_url)

        parsed_url = urlparse(authorization_url)
        url_parameters = parse_qs(parsed_url.query)
        decoded_state = json.loads(
            b64decode(url_parameters["state"][0].encode()).decode()
        )
        self.assertEqual(decoded_state["user_id"], self.user.id)

    def test_orcid_callback_succeeds_with_valid_authorization_code(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        mock_token_exchange.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
            "orcid": SAMPLE_ORCID_ID,
            "name": "Test User",
            "scope": "/read-limited",
        }

        oauth_state = self.encode_oauth_callback_state_data()
        response = self.client.get(
            f"{self.callback_endpoint}?code=valid-auth-code&state={oauth_state}"
        )

        self.assert_orcid_success_redirect(response)
        mock_sync_task.assert_called_once_with(self.user.id)

    def test_orcid_callback_fails_when_token_exchange_errors(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        token_exchange_error = HTTPError("400 Client Error")
        token_exchange_error.response = Mock(status_code=400)
        mock_token_exchange.side_effect = token_exchange_error

        oauth_state = self.encode_oauth_callback_state_data()
        response = self.client.get(
            f"{self.callback_endpoint}?code=invalid-auth-code&state={oauth_state}"
        )

        self.assert_orcid_failure_redirect(response)
        mock_sync_task.assert_not_called()

    def test_orcid_callback_fails_when_oauth_state_is_missing(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        response = self.client.get(f"{self.callback_endpoint}?code=some-auth-code")

        self.assert_orcid_failure_redirect(response)

    def test_orcid_callback_fails_when_user_does_not_exist(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        invalid_state = {"user_id": 99999, "return_to": "http://example.com"}
        encoded_state = b64encode(json.dumps(invalid_state).encode()).decode()
        response = self.client.get(
            f"{self.callback_endpoint}?code=some-auth-code&state={encoded_state}"
        )

        self.assert_orcid_failure_redirect(response)

    def test_orcid_callback_prevents_duplicate_account_linking(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        mock_token_exchange.return_value = {
            "access_token": "duplicate-access-token",
            "orcid": SAMPLE_ORCID_ID,
        }

        second_user = create_random_authenticated_user("second_user")
        self.setup_orcid_django_social_application()
        SocialAccount.objects.create(
            user=self.user, provider="orcid", uid=SAMPLE_ORCID_ID
        )

        duplicate_state = {
            "user_id": second_user.id,
            "return_to": "http://testserver/page",
        }
        encoded_state = b64encode(json.dumps(duplicate_state).encode()).decode()
        response = self.client.get(
            f"{self.callback_endpoint}?code=some-auth-code&state={encoded_state}"
        )

        self.assert_orcid_failure_redirect(response)
        self.assertIn("already+been+linked", response.url)
        mock_sync_task.assert_not_called()

    def test_publication_synchronization_updates_paper_metadata(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        mock_dois.return_value = [
            {"doi": "10.1111/test", "title": "Test Paper", "abstract": "Test Abstract"}
        ]
        mock_openalex.side_effect = lambda publications: None

        self.setup_user_orcid_account_with_token()
        self.create_test_author()
        Paper.objects.create(doi="10.1111/test", pdf_url="http://example.com/test.pdf")

        from oauth.services import sync_user_publications_from_orcid

        sync_user_publications_from_orcid(self.user)

        updated_paper = Paper.objects.get(doi__iexact="10.1111/test")
        self.assertEqual(updated_paper.title, "Test Paper")
        self.assertEqual(updated_paper.abstract, "Test Abstract")
        mock_pdf_download.delay.assert_called_once_with(updated_paper.id)

    def test_authorship_creation_links_user_to_papers(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        from oauth.services import create_user_authorships

        user_author = self.create_test_author()

        first_paper = Paper.objects.create(doi="10.1111/test1", title="Paper 1")
        second_paper = Paper.objects.create(doi="10.1111/test2", title="Paper 2")

        create_user_authorships(self.user, ["10.1111/test1", "10.1111/test2"])

        first_authorship = Authorship.objects.filter(
            author=user_author, paper=first_paper
        ).first()
        second_authorship = Authorship.objects.filter(
            author=user_author, paper=second_paper
        ).first()

        self.assertIsNotNone(first_authorship)
        self.assertIsNotNone(second_authorship)

        expected_author_name = (
            f"{user_author.first_name} {user_author.last_name}".strip()
        )
        self.assertEqual(first_authorship.raw_author_name, expected_author_name)
        self.assertEqual(first_authorship.author_position, "middle")

        initial_authorship_count = Authorship.objects.count()
        create_user_authorships(self.user, ["10.1111/test1", "10.1111/test2"])
        self.assertEqual(Authorship.objects.count(), initial_authorship_count)

    def test_celery_task_processes_publications_successfully(
        self,
        mock_http_session,
        mock_token_exchange,
        mock_sync_task,
        mock_dois,
        mock_openalex,
        mock_pdf_download,
    ):
        mock_dois.return_value = [
            {"doi": "10.2222/task", "title": "Task Paper", "abstract": "Task Abstract"}
        ]

        self.setup_user_orcid_account_with_token("task-access-token")
        self.create_test_author({"first_name": "Task", "last_name": "User"})
        Paper.objects.create(doi="10.2222/task", pdf_url="http://example.com/task.pdf")

        from oauth.tasks import sync_orcid_publications

        sync_orcid_publications(self.user.id)

        processed_paper = Paper.objects.get(doi__iexact="10.2222/task")
        self.assertEqual(processed_paper.title, "Task Paper")
