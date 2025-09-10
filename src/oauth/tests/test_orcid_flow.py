import json
from base64 import b64encode
from unittest.mock import Mock, patch

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib.sites.models import Site
from django.test import override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.models import Author
from user.tests.helpers import create_random_authenticated_user

# run these with python src/manage.py test oauth.tests.test_orcid_flow.OrcidFlowTests
ORCID_SETTINGS = dict(
    ORCID_CLIENT_ID="test-client",
    ORCID_CLIENT_SECRET="test-secret",
    ORCID_REDIRECT_URL="http://testserver/orcid/callback",
    ORCID_BASE_URL="http://orcid.test",
    ORCID_SCOPE="/read-limited",
)


@override_settings(**ORCID_SETTINGS)
class OrcidFlowTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("orcid_flow_user")
        self.token = Token.objects.get(user=self.user)
        # Ensure current Site exists so SocialApp can attach
        Site.objects.get_or_create(
            id=1, defaults={"domain": "testserver", "name": "test"}
        )

        # Resolve named routes (matches urls.py)
        self.auth_url_endpoint = reverse("orcid_connect")
        self.check_url = reverse("orcid_check")
        self.callback_url = reverse("orcid_callback")
        self.sync_url = reverse("orcid_sync")

    def tearDown(self):
        # Clean up test data to avoid constraint violations between tests
        SocialToken.objects.filter(account__user=self.user).delete()
        SocialAccount.objects.filter(user=self.user).delete()
        Authorship.objects.filter(author__user=self.user).delete()
        Author.objects.filter(user=self.user).delete()
        Paper.objects.all().delete()  # Clean up test papers

    def auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Token {self.token.key}"}

    def _ensure_app(self):
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

    def test_check_returns_false_without_token(self):
        resp = self.client.get(self.check_url, **self.auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["authenticated"])
        self.assertTrue(resp.data["needs_reauth"])
        self.assertIsNone(resp.data["orcid_id"])
        self.assertEqual(
            resp.data["error"],
            "No ORCID account connected. Please connect your ORCID account.",
        )

    @patch("utils.retryable_requests.retryable_requests_session")
    def test_check_validates_token_with_orcid_api(self, mock_session):
        app = self._ensure_app()
        acc, _ = SocialAccount.objects.get_or_create(
            user=self.user, provider="orcid", uid="0000-0002-1825-0097"
        )
        SocialToken.objects.get_or_create(
            app=app, account=acc, defaults={"token": "access-123"}
        )

        # Mock successful ORCID API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/vnd.orcid+json"}
        mock_session.return_value.__enter__.return_value.get.return_value = (
            mock_response
        )

        resp = self.client.get(self.check_url, **self.auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["authenticated"])
        self.assertFalse(resp.data["needs_reauth"])
        self.assertEqual(resp.data["orcid_id"], "0000-0002-1825-0097")
        self.assertIsNone(resp.data["error"])

    @patch("utils.retryable_requests.retryable_requests_session")
    def test_check_detects_invalid_token(self, mock_session):
        app = self._ensure_app()
        acc, _ = SocialAccount.objects.get_or_create(
            user=self.user, provider="orcid", uid="0000-0002-1825-0097"
        )
        SocialToken.objects.get_or_create(
            app=app, account=acc, defaults={"token": "invalid-token"}
        )

        # Mock HTML response (invalid token)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_session.return_value.__enter__.return_value.get.return_value = (
            mock_response
        )

        resp = self.client.get(self.check_url, **self.auth_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["authenticated"])
        self.assertTrue(resp.data["needs_reauth"])
        self.assertEqual(resp.data["orcid_id"], "0000-0002-1825-0097")
        self.assertEqual(
            resp.data["error"],
            "Your ORCID access has expired. Please reconnect your ORCID account.",
        )

    @patch("oauth.tasks.sync_orcid_for_user_task.delay")
    def test_sync_enqueues_celery_task(self, mock_task):
        # Arrange existing token
        app = self._ensure_app()
        acc, _ = SocialAccount.objects.get_or_create(
            user=self.user, provider="orcid", uid="0000-0002-1825-0097"
        )
        SocialToken.objects.get_or_create(
            app=app, account=acc, defaults={"token": "access-123"}
        )

        resp = self.client.post(self.sync_url, {}, format="json", **self.auth_headers())

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get("ok"))
        mock_task.assert_called_once_with(self.user.id)

    @patch("oauth.services.download_pdf")
    @patch("oauth.services.process_openalex_works")
    @patch(
        "oauth.services.OpenAlex.get_data_from_doi",
        return_value={"id": "https://openalex.org/W123", "doi": "10.1111/foo"},
    )
    @patch(
        "oauth.services.list_user_dois",
        return_value=[
            {"doi": "10.1111/foo", "title": "ORCID T", "abstract": "ORCID A"}
        ],
    )
    def test_service_overlay_and_pdf_queue_after_pipeline(
        self, _mock_list, _mock_get, mock_process, mock_dl
    ):
        # Arrange existing token
        app = self._ensure_app()
        acc, _ = SocialAccount.objects.get_or_create(
            user=self.user, provider="orcid", uid="0000-0002-1825-0097"
        )
        SocialToken.objects.get_or_create(
            app=app, account=acc, defaults={"token": "access-123"}
        )

        # Create Author profile for the user first
        Author.objects.get_or_create(
            user=self.user, defaults={"first_name": "Test", "last_name": "User"}
        )

        # Existing Paper with missing title/abstract but known pdf_url
        Paper.objects.create(
            doi="10.1111/foo",
            url="http://example.com",
            pdf_url="http://example.com/foo.pdf",
        )

        mock_process.side_effect = lambda works: None  # no-op

        # Test the service function directly
        from oauth.services import sync_orcid_for_user

        sync_orcid_for_user(self.user)

        p = Paper.objects.get(doi__iexact="10.1111/foo")
        self.assertEqual(p.title, "ORCID T")
        self.assertEqual(p.abstract, "ORCID A")
        mock_dl.delay.assert_called_once_with(p.id)

        # Verify authorship was created
        author = Author.objects.get(user=self.user)
        authorship = Authorship.objects.filter(author=author, paper=p).first()
        self.assertIsNotNone(authorship, "Authorship should have been created")
        self.assertEqual(authorship.author_position, "middle")
        self.assertFalse(authorship.is_corresponding)

    @patch("oauth.tasks.sync_orcid_for_user_task.delay")
    @patch(
        "oauth.orcid_views.exchange_code_for_token",
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "orcid": "0000-0002-1825-0097",
            "name": "Jane Doe",
            "scope": "/read-limited",
        },
    )
    def test_callback_creates_tokens_enqueues_sync_and_redirects(
        self, mock_exchange, mock_task
    ):
        # Use new direct callback format with user_id in state
        state_data = {
            "user_id": self.user.id,
            "return_to": "http://testserver/some/page",
        }
        state = b64encode(json.dumps(state_data).encode("utf-8")).decode("utf-8")

        # Call callback without auth headers (direct from ORCID)
        resp = self.client.get(f"{self.callback_url}?code=abc&state={state}")

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("http://testserver/some/page"))
        self.assertIn("orcid_sync=ok", resp.url)
        self.assertIn(f"user_id={self.user.id}", resp.url)

        # Verify token creation
        app = SocialApp.objects.get(provider="orcid")
        acc = SocialAccount.objects.get(user=self.user, provider="orcid")
        tok = SocialToken.objects.get(app=app, account=acc)
        self.assertEqual(tok.token, "new-access")
        self.assertEqual(tok.token_secret, "new-refresh")

        # Verify Celery task was enqueued
        mock_task.assert_called_once_with(self.user.id)

    @patch("oauth.services.download_pdf")
    @patch("oauth.services.process_openalex_works")
    @patch(
        "oauth.services.OpenAlex.get_data_from_doi",
        return_value={"id": "https://openalex.org/W456", "doi": "10.2222/bar"},
    )
    @patch(
        "oauth.services.list_user_dois",
        return_value=[
            {"doi": "10.2222/bar", "title": "Task Title", "abstract": "Task Abstract"}
        ],
    )
    def test_celery_task_calls_service_function(
        self, _mock_list, _mock_get, mock_process, mock_dl
    ):
        # Arrange existing token
        app = self._ensure_app()
        acc, _ = SocialAccount.objects.get_or_create(
            user=self.user, provider="orcid", uid="0000-0002-1825-0097"
        )
        SocialToken.objects.get_or_create(
            app=app, account=acc, defaults={"token": "access-456"}
        )

        # Create Author profile for the user
        Author.objects.get_or_create(
            user=self.user, defaults={"first_name": "Task", "last_name": "User"}
        )

        # Existing Paper to test overlay
        Paper.objects.create(
            doi="10.2222/bar",
            url="http://example.com/bar",
            pdf_url="http://example.com/bar.pdf",
        )

        mock_process.side_effect = lambda works: None  # no-op

        # Test the Celery task directly
        from oauth.tasks import sync_orcid_for_user_task

        sync_orcid_for_user_task(self.user.id)

        p = Paper.objects.get(doi__iexact="10.2222/bar")
        self.assertEqual(p.title, "Task Title")
        self.assertEqual(p.abstract, "Task Abstract")
        mock_dl.delay.assert_called_once_with(p.id)

    @patch("oauth.tasks.sync_orcid_for_user_task.delay")
    @patch("oauth.orcid_views.exchange_code_for_token")
    def test_callback_handles_token_exchange_error(self, mock_exchange, mock_task):
        """Test that callback handles ORCID token exchange errors gracefully."""
        from unittest.mock import Mock

        from requests.exceptions import HTTPError

        # Mock an HTTP error response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.reason = "Bad Request"
        mock_response.json.return_value = {
            "error_description": "Invalid authorization code"
        }

        http_error = HTTPError("400 Client Error")
        http_error.response = mock_response
        mock_exchange.side_effect = http_error

        # Use new direct callback format with user_id in state
        state_data = {
            "user_id": self.user.id,
            "return_to": "http://127.0.0.1:3000/author/1",
        }
        state = b64encode(json.dumps(state_data).encode("utf-8")).decode("utf-8")

        # Call callback without auth headers (direct from ORCID)
        resp = self.client.get(f"{self.callback_url}?code=invalid_code&state={state}")

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("http://127.0.0.1:3000/author/1"))
        self.assertIn("orcid_sync=fail", resp.url)
        self.assertIn(
            "error=ORCID%20connection%20failed.%20Please%20try%20again.", resp.url
        )
        mock_task.assert_not_called()

    def test_create_orcid_authorships_function(self):
        """Test the _create_orcid_authorships helper function directly."""
        from oauth.services import _create_orcid_authorships

        # Create Author and Papers
        author, _ = Author.objects.get_or_create(
            user=self.user, defaults={"first_name": "John", "last_name": "Doe"}
        )
        paper1 = Paper.objects.create(doi="10.1111/test1", title="Test Paper 1")
        paper2 = Paper.objects.create(doi="10.1111/test2", title="Test Paper 2")

        # Create authorships
        dois = ["10.1111/test1", "10.1111/test2"]
        _create_orcid_authorships(self.user, dois)

        # Verify authorships were created
        auth1 = Authorship.objects.filter(author=author, paper=paper1).first()
        auth2 = Authorship.objects.filter(author=author, paper=paper2).first()

        self.assertIsNotNone(auth1)
        self.assertIsNotNone(auth2)
        # Check that raw_author_name uses the Author's first and last name
        expected_name = f"{author.first_name} {author.last_name}".strip()
        self.assertEqual(auth1.raw_author_name, expected_name)
        self.assertEqual(auth2.raw_author_name, expected_name)
        self.assertEqual(auth1.author_position, "middle")
        self.assertEqual(auth2.author_position, "middle")

        # Test no duplicate creation
        initial_count = Authorship.objects.count()
        _create_orcid_authorships(self.user, dois)  # Call again
        self.assertEqual(
            Authorship.objects.count(), initial_count, "Should not create duplicates"
        )

    def test_auth_url_generation(self):
        """Test the auth URL generation endpoint."""
        resp = self.client.get(
            f"{self.auth_url_endpoint}?return_to=http://example.com/success",
            **self.auth_headers(),
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("auth_url", resp.data)
        self.assertEqual(resp.data["user_id"], self.user.id)

        # Verify the auth URL contains expected parameters
        auth_url = resp.data["auth_url"]
        # Use test URL from settings
        self.assertIn("orcid.test/oauth/authorize", auth_url)
        self.assertIn("state=", auth_url)
        self.assertIn("client_id=", auth_url)
        self.assertIn("response_type=code", auth_url)

        # Decode and verify state parameter
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(auth_url)
        params = parse_qs(parsed.query)
        state_encoded = params["state"][0]

        import base64

        state_decoded = json.loads(base64.b64decode(state_encoded).decode("utf-8"))
        self.assertEqual(state_decoded["user_id"], self.user.id)
        self.assertEqual(state_decoded["return_to"], "http://example.com/success")

    def test_callback_missing_state(self):
        """Test callback with missing state parameter."""
        resp = self.client.get(f"{self.callback_url}?code=abc")

        self.assertEqual(resp.status_code, 302)
        self.assertIn("orcid_sync=fail", resp.url)
        self.assertIn(
            "error=ORCID%20authorization%20session%20expired.%20Please%20try%20again.",
            resp.url,
        )

    def test_callback_invalid_user_id(self):
        """Test callback with invalid user ID in state."""
        state_data = {"user_id": 99999, "return_to": "http://example.com"}
        state = b64encode(json.dumps(state_data).encode("utf-8")).decode("utf-8")

        resp = self.client.get(f"{self.callback_url}?code=abc&state={state}")

        self.assertEqual(resp.status_code, 302)
        self.assertIn("orcid_sync=fail", resp.url)
        self.assertIn(
            "error=Your%20account%20session%20has%20expired.%20"
            "Please%20log%20in%20and%20try%20again.",
            resp.url,
        )

    @patch("oauth.tasks.sync_orcid_for_user_task.delay")
    @patch(
        "oauth.orcid_views.exchange_code_for_token",
        return_value={
            "access_token": "duplicate-access",
            "refresh_token": "duplicate-refresh",
            "expires_in": 3600,
            "orcid": "0000-0002-1825-0097",  # Same ORCID as other tests
            "name": "Duplicate User",
            "scope": "/read-limited",
        },
    )
    def test_callback_prevents_duplicate_orcid_linking(self, mock_exchange, mock_task):
        """Test that linking the same ORCID to different users is prevented."""
        from allauth.socialaccount.models import SocialAccount

        from user.tests.helpers import create_random_authenticated_user

        # Create a second user
        second_user = create_random_authenticated_user("second_orcid_user")

        # First, link the ORCID to the original user
        self._ensure_app()
        SocialAccount.objects.get_or_create(
            user=self.user, provider="orcid", uid="0000-0002-1825-0097"
        )

        # Now try to link the same ORCID to the second user
        state_data = {
            "user_id": second_user.id,
            "return_to": "http://testserver/some/page",
        }
        state = b64encode(json.dumps(state_data).encode("utf-8")).decode("utf-8")

        # Call callback for second user with same ORCID
        resp = self.client.get(f"{self.callback_url}?code=abc&state={state}")

        self.assertEqual(resp.status_code, 302)
        self.assertIn("orcid_sync=fail", resp.url)
        self.assertIn(
            "This%20ORCID%20account%20has%20already%20been%20linked%20"
            "to%20another%20user.",
            resp.url,
        )
        mock_task.assert_not_called()  # Sync should not be triggered
