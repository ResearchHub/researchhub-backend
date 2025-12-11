from unittest.mock import Mock, patch

from allauth.socialaccount.models import SocialAccount, SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.core.cache import cache
from django.test import TestCase

from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from orcid.services.orcid_service import (
    ORCID_BASE_URL,
    build_auth_url,
    connect_orcid_account,
    exchange_code_for_token,
    extract_dois_from_orcid_works,
    extract_orcid_id,
    fetch_orcid_works,
    get_author_position_from_work,
    get_orcid_app,
    is_orcid_connected,
    link_papers_to_author,
    sync_orcid_papers,
)
from orcid.tests.helpers import create_orcid_app
from user.related_models.author_model import Author
from user.tests.helpers import create_random_default_user


class OrcidServiceTests(TestCase):
    def test_is_connected_returns_false_for_none(self):
        self.assertFalse(is_orcid_connected(None))

    def test_is_connected_returns_false_when_not_linked(self):
        user = create_random_default_user("unlinked")
        self.assertFalse(is_orcid_connected(user))

    def test_is_connected_returns_true_when_linked(self):
        user = create_random_default_user("linked")
        SocialAccount.objects.create(user=user, provider=OrcidProvider.id, uid="123")
        self.assertTrue(is_orcid_connected(user))

    def test_get_app_returns_app(self):
        app = create_orcid_app()
        self.assertEqual(get_orcid_app(), app)

    def test_get_app_raises_when_missing(self):
        with self.assertRaises(SocialApp.DoesNotExist):
            get_orcid_app()

    def test_build_auth_url(self):
        app = create_orcid_app()
        url = build_auth_url(app, 123)
        self.assertIn("test-id", url)
        self.assertIn("123", url)

    def test_connect_creates_account(self):
        user = create_random_default_user("new")
        connect_orcid_account(user, {"orcid": "0000-0001-2345-6789"})
        self.assertTrue(SocialAccount.objects.filter(user=user).exists())

    def test_connect_updates_author(self):
        user = create_random_default_user("author")
        connect_orcid_account(user, {"orcid": "0000-0001-2345-6789"})
        user.author_profile.refresh_from_db()
        self.assertEqual(user.author_profile.orcid_id, f"{ORCID_BASE_URL}/0000-0001-2345-6789")

    def test_connect_raises_on_invalid_response(self):
        user = create_random_default_user("invalid")
        with self.assertRaises(ValueError):
            connect_orcid_account(user, {})

    def test_connect_raises_when_already_linked(self):
        user1 = create_random_default_user("user1")
        user2 = create_random_default_user("user2")
        SocialAccount.objects.create(
            user=user1, provider=OrcidProvider.id, uid="0000-0001-2345-6789"
        )
        with self.assertRaises(ValueError):
            connect_orcid_account(user2, {"orcid": "0000-0001-2345-6789"})

    @patch("orcid.services.orcid_service.requests.post")
    def test_exchange_code(self, mock_post):
        mock_post.return_value = Mock(json=lambda: {"orcid": "123"}, raise_for_status=Mock())
        app = create_orcid_app()
        result = exchange_code_for_token(app, "code")
        self.assertEqual(result["orcid"], "123")

    def test_extract_orcid_id_from_url(self):
        result = extract_orcid_id("https://orcid.org/0000-0001-2345-6789")
        self.assertEqual(result, "0000-0001-2345-6789")

    def test_extract_orcid_id_returns_none_for_empty(self):
        self.assertIsNone(extract_orcid_id(None))
        self.assertIsNone(extract_orcid_id(""))

    def test_extract_dois_from_orcid_works(self):
        orcid_data = {
            "group": [
                {
                    "work-summary": [
                        {
                            "external-ids": {
                                "external-id": [
                                    {"external-id-type": "doi", "external-id-value": "10.1234/test"}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        dois = extract_dois_from_orcid_works(orcid_data)
        self.assertEqual(dois, ["10.1234/test"])

    def test_extract_dois_returns_empty_for_no_dois(self):
        self.assertEqual(extract_dois_from_orcid_works({"group": []}), [])

    @patch("orcid.services.orcid_service.requests.get")
    def test_fetch_orcid_works(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"group": []}, raise_for_status=Mock())
        result = fetch_orcid_works("0000-0001-2345-6789")
        self.assertEqual(result, {"group": []})
        mock_get.assert_called_once()

    @patch("orcid.services.orcid_service.link_papers_to_author")
    @patch("orcid.services.orcid_service.process_openalex_works")
    @patch("orcid.services.orcid_service.OpenAlex")
    @patch("orcid.services.orcid_service.fetch_orcid_works")
    def test_sync_orcid_papers(self, mock_fetch, mock_openalex_class, mock_process, mock_link):
        user = create_random_default_user("sync_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        mock_fetch.return_value = {
            "group": [
                {
                    "work-summary": [
                        {
                            "external-ids": {
                                "external-id": [
                                    {"external-id-type": "doi", "external-id-value": "10.1234/test"}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        mock_openalex = Mock()
        mock_openalex_class.return_value = mock_openalex
        mock_openalex.get_work_by_doi.return_value = {"doi": "10.1234/test", "title": "Test"}
        mock_link.return_value = 1

        result = sync_orcid_papers(user.author_profile.id)

        self.assertEqual(result["papers_processed"], 1)
        mock_fetch.assert_called_once_with("0000-0001-2345-6789")
        mock_process.assert_called_once()
        mock_link.assert_called_once()

    def test_sync_raises_when_no_orcid(self):
        user = create_random_default_user("no_orcid")
        with self.assertRaises(ValueError):
            sync_orcid_papers(user.author_profile.id)

    @patch("orcid.services.orcid_service.fetch_orcid_works")
    def test_sync_returns_zero_when_no_dois(self, mock_fetch):
        user = create_random_default_user("nodois_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        mock_fetch.return_value = {"group": [{"work-summary": [{"external-ids": {}}]}]}
        result = sync_orcid_papers(user.author_profile.id)
        self.assertEqual(result["papers_processed"], 0)

    def test_get_author_position_returns_position_when_matched(self):
        work = {
            "authorships": [
                {"author": {"orcid": "https://orcid.org/0000-0001"}, "author_position": "first"}
            ]
        }
        self.assertEqual(get_author_position_from_work(work, "0000-0001"), "first")

    def test_get_author_position_returns_middle_when_not_matched(self):
        work = {
            "authorships": [
                {"author": {"orcid": "https://orcid.org/9999-9999"}, "author_position": "first"}
            ]
        }
        self.assertEqual(
            get_author_position_from_work(work, "0000-0001"),
            Authorship.MIDDLE_AUTHOR_POSITION,
        )

    def test_link_papers_to_author_creates_authorship(self):
        user = create_random_default_user("link_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        paper = Paper.objects.create(doi="10.1234/link-test", title="Link Test")
        works = [{"doi": "https://doi.org/10.1234/link-test", "authorships": []}]

        count = link_papers_to_author(user.author_profile, works)

        self.assertEqual(count, 1)
        self.assertTrue(
            Authorship.objects.filter(paper=paper, author=user.author_profile).exists()
        )

    def test_link_papers_uses_correct_position(self):
        user = create_random_default_user("position_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        paper = Paper.objects.create(doi="10.1234/position-test", title="Position Test")
        works = [{
            "doi": "https://doi.org/10.1234/position-test",
            "authorships": [{
                "author": {"orcid": "https://orcid.org/0000-0001-2345-6789"},
                "author_position": "first",
            }]
        }]

        link_papers_to_author(user.author_profile, works)

        authorship = Authorship.objects.get(paper=paper, author=user.author_profile)
        self.assertEqual(authorship.author_position, "first")

    def test_link_papers_clears_cache(self):
        user = create_random_default_user("cache_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        cache_key = f"author-{user.author_profile.id}-publications"
        cache.set(cache_key, ["stale_data"])

        paper = Paper.objects.create(doi="10.1234/cache-test", title="Cache Test")
        works = [{"doi": "https://doi.org/10.1234/cache-test", "authorships": []}]

        link_papers_to_author(user.author_profile, works)

        self.assertIsNone(cache.get(cache_key))

    def test_link_papers_does_not_clear_cache_when_nothing_linked(self):
        user = create_random_default_user("nocache_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        cache_key = f"author-{user.author_profile.id}-publications"
        cache.set(cache_key, ["cached_data"])

        works = [{"doi": "https://doi.org/10.1234/nonexistent", "authorships": []}]
        link_papers_to_author(user.author_profile, works)

        self.assertEqual(cache.get(cache_key), ["cached_data"])

    def test_link_papers_skips_missing_doi(self):
        user = create_random_default_user("nodoi_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        works = [{"authorships": []}]
        count = link_papers_to_author(user.author_profile, works)
        self.assertEqual(count, 0)

    def test_link_papers_skips_missing_paper(self):
        user = create_random_default_user("nopaper_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        works = [{"doi": "https://doi.org/10.1234/nonexistent", "authorships": []}]
        count = link_papers_to_author(user.author_profile, works)
        self.assertEqual(count, 0)

    def test_link_papers_handles_empty_works(self):
        user = create_random_default_user("empty_user")
        user.author_profile.orcid_id = "https://orcid.org/0000-0001-2345-6789"
        user.author_profile.save()

        count = link_papers_to_author(user.author_profile, [])
        self.assertEqual(count, 0)

    def test_sync_raises_when_author_not_found(self):
        with self.assertRaises(Author.DoesNotExist):
            sync_orcid_papers(999999)

