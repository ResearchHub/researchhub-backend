import base64
import json
from base64 import b64encode
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

# run these with python src/manage.py test oauth.tests.test_orcid_flow.OrcidTests
ORCID_SETTINGS = {
    "ORCID_CLIENT_ID": "test-client",
    "ORCID_CLIENT_SECRET": "test-secret",
    "ORCID_REDIRECT_URL": "http://testserver/orcid/callback",
    "ORCID_BASE_URL": "http://orcid.test",
    "ORCID_SCOPE": "/read-limited",
}


@override_settings(**ORCID_SETTINGS)
class OrcidTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = create_random_authenticated_user("test_user")
        self.token = Token.objects.get(user=self.user)
        Site.objects.get_or_create(
            id=1, defaults={"domain": "testserver", "name": "test"}
        )
        self.connect_url = reverse("orcid_connect")
        self.check_url = reverse("orcid_check")
        self.callback_url = reverse("orcid_callback")
        self.sync_url = reverse("orcid_sync")

    def tearDown(self):
        Authorship.objects.all().delete()
        SocialToken.objects.all().delete()
        SocialAccount.objects.all().delete()
        Author.objects.all().delete()
        Paper.objects.all().delete()
        if hasattr(self, "token"):
            self.token.delete()
        if hasattr(self, "user"):
            self.user.delete()

    def auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def create_orcid_app(self):
        app, _ = SocialApp.objects.get_or_create(
            provider="orcid",
            defaults={
                "name": "ORCID",
                "client_id": ORCID_SETTINGS["ORCID_CLIENT_ID"],
                "secret": ORCID_SETTINGS["ORCID_CLIENT_SECRET"],
            },
        )
        site = Site.objects.get_current()
        if site not in app.sites.all():
            app.sites.add(site)
        return app

    def create_orcid_account(self, token="access-123"):
        app = self.create_orcid_app()
        acc, _ = SocialAccount.objects.get_or_create(
            user=self.user, provider="orcid", uid="0000-0002-1825-0097"
        )
        SocialToken.objects.get_or_create(
            app=app, account=acc, defaults={"token": token}
        )
        return app, acc

    def create_test_state(self, return_to="http://testserver/page"):
        state_data = {"user_id": self.user.id, "return_to": return_to}
        return b64encode(json.dumps(state_data).encode()).decode()

    def test_check_without_connection(self):
        resp = self.client.post(
            self.check_url, {}, format="json", **self.auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("connected", resp.data)
        self.assertFalse(resp.data["connected"])
        self.assertIn("error", resp.data)

    @patch("utils.retryable_requests.retryable_requests_session")
    def test_check_with_valid_connection(self, mock_session):
        self.create_orcid_account()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/vnd.orcid+json"}
        mock_session.return_value.__enter__.return_value.get.return_value = (
            mock_response
        )

        resp = self.client.post(
            self.check_url, {}, format="json", **self.auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        # Debug: Print response to understand why connected is False
        print(f"Valid connection test response: {resp.data}")
        self.assertIn("connected", resp.data)
        self.assertTrue(resp.data["connected"])
        self.assertIn("error", resp.data)
        self.assertIsNone(resp.data["error"])

    @patch("utils.retryable_requests.retryable_requests_session")
    def test_check_with_expired_token(self, mock_session):
        self.create_orcid_account("invalid-token")
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_session.return_value.__enter__.return_value.get.return_value = (
            mock_response
        )

        resp = self.client.post(
            self.check_url, {}, format="json", **self.auth_headers()
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("connected", resp.data)
        self.assertFalse(resp.data["connected"])
        self.assertIn("error", resp.data)
        self.assertIsNotNone(resp.data["error"])

    @patch("oauth.tasks.sync_orcid_for_user_task.delay")
    def test_sync_triggers_task(self, mock_task):
        self.create_orcid_account()
        resp = self.client.post(self.sync_url, {}, format="json", **self.auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get("ok"))
        mock_task.assert_called_once_with(self.user.id)

    def test_connect_url_generation(self):
        resp = self.client.post(
            self.connect_url,
            {"return_to": "http://example.com/success"},
            format="json",
            **self.auth_headers(),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("auth_url", resp.data)
        self.assertEqual(resp.data["user_id"], self.user.id)
        auth_url = resp.data["auth_url"]
        self.assertIn("orcid.test/oauth/authorize", auth_url)
        self.assertIn("state=", auth_url)
        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        state_decoded = json.loads(base64.b64decode(params["state"][0]).decode())
        self.assertEqual(state_decoded["user_id"], self.user.id)

    @patch("oauth.tasks.sync_orcid_for_user_task.delay")
    @patch("oauth.orcid_views.exchange_orcid_code_for_tokens")
    def test_successful_callback(self, mock_exchange, mock_task):
        mock_exchange.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "orcid": "0000-0002-1825-0097",
            "name": "Test User",
            "scope": "/read-limited",
        }
        state = self.create_test_state()
        resp = self.client.get(f"{self.callback_url}?code=abc&state={state}")

        self.assertEqual(resp.status_code, 302)
        self.assertIn("orcid_sync=ok", resp.url)
        self.assertIn(f"user_id={self.user.id}", resp.url)
        mock_task.assert_called_once_with(self.user.id)

    @patch("oauth.tasks.sync_orcid_for_user_task.delay")
    @patch("oauth.orcid_views.exchange_orcid_code_for_tokens")
    def test_callback_with_exchange_error(self, mock_exchange, mock_task):
        mock_response = Mock()
        mock_response.status_code = 400
        http_error = HTTPError("400 Client Error")
        http_error.response = mock_response
        mock_exchange.side_effect = http_error

        state = self.create_test_state()
        resp = self.client.get(f"{self.callback_url}?code=invalid&state={state}")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("orcid_sync=fail", resp.url)
        mock_task.assert_not_called()

    def test_callback_missing_state(self):
        resp = self.client.get(f"{self.callback_url}?code=abc")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("orcid_sync=fail", resp.url)

    def test_callback_invalid_user(self):
        state_data = {"user_id": 99999, "return_to": "http://example.com"}
        state = b64encode(json.dumps(state_data).encode()).decode()
        resp = self.client.get(f"{self.callback_url}?code=abc&state={state}")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("orcid_sync=fail", resp.url)

    @patch("oauth.tasks.sync_orcid_for_user_task.delay")
    @patch("oauth.orcid_views.exchange_orcid_code_for_tokens")
    def test_duplicate_orcid_prevention(self, mock_exchange, mock_task):
        mock_exchange.return_value = {
            "access_token": "duplicate-access",
            "orcid": "0000-0002-1825-0097",
        }
        second_user = create_random_authenticated_user("second_user")
        self.create_orcid_app()
        SocialAccount.objects.create(
            user=self.user, provider="orcid", uid="0000-0002-1825-0097"
        )

        state_data = {"user_id": second_user.id, "return_to": "http://testserver/page"}
        state = b64encode(json.dumps(state_data).encode()).decode()
        resp = self.client.get(f"{self.callback_url}?code=abc&state={state}")

        self.assertEqual(resp.status_code, 302)
        self.assertIn("orcid_sync=fail", resp.url)
        self.assertIn("already%20been%20linked", resp.url)
        mock_task.assert_not_called()

    @patch("oauth.services.get_user_publication_dois")
    @patch("oauth.services.process_openalex_works")
    @patch("oauth.services.download_pdf")
    def test_publication_sync(self, mock_dl, mock_process, mock_dois):
        mock_dois.return_value = [
            {"doi": "10.1111/test", "title": "Test Paper", "abstract": "Test Abstract"}
        ]
        mock_process.side_effect = lambda x: None
        self.create_orcid_account()
        author, _ = Author.objects.get_or_create(
            user=self.user, defaults={"first_name": "Test", "last_name": "User"}
        )
        Paper.objects.create(doi="10.1111/test", pdf_url="http://example.com/test.pdf")

        from oauth.services import sync_user_publications_from_orcid

        sync_user_publications_from_orcid(self.user)

        paper = Paper.objects.get(doi__iexact="10.1111/test")
        self.assertEqual(paper.title, "Test Paper")
        self.assertEqual(paper.abstract, "Test Abstract")
        mock_dl.delay.assert_called_once_with(paper.id)

    def test_authorship_creation(self):
        from oauth.services import create_author_paper_relationships

        author, _ = Author.objects.get_or_create(
            user=self.user, defaults={"first_name": "Test", "last_name": "User"}
        )
        paper1 = Paper.objects.create(doi="10.1111/test1", title="Paper 1")
        paper2 = Paper.objects.create(doi="10.1111/test2", title="Paper 2")

        create_author_paper_relationships(self.user, ["10.1111/test1", "10.1111/test2"])

        auth1 = Authorship.objects.filter(author=author, paper=paper1).first()
        auth2 = Authorship.objects.filter(author=author, paper=paper2).first()
        self.assertIsNotNone(auth1)
        self.assertIsNotNone(auth2)
        # The raw_author_name should match the author's actual name
        expected_name = f"{author.first_name} {author.last_name}".strip()
        self.assertEqual(auth1.raw_author_name, expected_name)
        self.assertEqual(auth1.author_position, "middle")

        initial_count = Authorship.objects.count()
        create_author_paper_relationships(self.user, ["10.1111/test1", "10.1111/test2"])
        self.assertEqual(Authorship.objects.count(), initial_count)

    @patch("oauth.services.get_user_publication_dois")
    def test_celery_task(self, mock_dois):
        mock_dois.return_value = [
            {"doi": "10.2222/task", "title": "Task Paper", "abstract": "Task Abstract"}
        ]
        self.create_orcid_account("access-456")
        Author.objects.get_or_create(
            user=self.user, defaults={"first_name": "Task", "last_name": "User"}
        )
        Paper.objects.create(doi="10.2222/task", pdf_url="http://example.com/task.pdf")

        from oauth.tasks import sync_orcid_for_user_task

        sync_orcid_for_user_task(self.user.id)

        paper = Paper.objects.get(doi__iexact="10.2222/task")
        self.assertEqual(paper.title, "Task Paper")
