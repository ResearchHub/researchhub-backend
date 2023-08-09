from citation.constants import JOURNAL_ARTICLE
from researchhub_access_group.models import Permission
from user.tests.helpers import create_random_default_user
from utils.test_helpers import APITestCaseWithOrg


class CitationEntryViewTests(APITestCaseWithOrg):
    def setUp(self):
        self.authenticated_user = create_random_default_user("user1")
        self.random_user = create_random_default_user("random1")
        self.organization_user = create_random_default_user("orguser1")

    def test_create_citation(self):
        self.client.force_authenticate(self.authenticated_user)
        response = self.client.post(
            "/api/citation_entry/",
            {
                "fields": {
                    "creators": [{"first_name": "Test", "last_name": "Author"}],
                    "title": "Test Article",
                    "abstract_note": "",
                    "publication_title": "Neonatal Fc receptor is a functional receptor for human astrovirus",
                    "volume": "",
                    "issue": "",
                    "pages": "",
                    "date": "11-13-2022",
                    "series": "",
                    "series_title": "",
                    "series_text": "",
                    "journal_abbreviation": "",
                    "language": "",
                    "DOI": "10.1101/2022.11.13.516297",
                    "ISSN": "",
                    "short_title": "",
                    "url": "",
                    "access_date": "08-08-2023",
                    "archive": "",
                    "archive_location": "",
                    "library_catalog": "",
                    "call_number": "",
                    "rights": "",
                    "extra": "",
                },
                "citation_type": JOURNAL_ARTICLE,
                "doi": "10.1101/2022.11.13.516297",
                "organization": self.authenticated_user.organization.id,
            },
        )
        self.assertEqual(response.status_code, 201)
        return response

    def test_url_search(self):
        self.client.force_authenticate(self.authenticated_user)

        response = self.client.get(
            "/api/citation_entry/url_search/?url=https://staging-backend.researchhub.com/api/paper/1001/",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["doi"], "https://doi.org/10.1016/0370-2693(93)90747-6"
        )

    def test_create_private_comment(self):
        citation = self.test_create_citation()
        data = citation.data
        citation_id = data.get("id")

        self.client.force_authenticate(self.authenticated_user)
        response = self.client.post(
            f"/api/citation/{citation_id}/comments/create_rh_comment/",
            {
                "comment_content_json": {"ops": [{"insert": "test"}]},
                "thread_type": "GENERIC_COMMENT",
                "privacy_type": "PRIVATE",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response, citation

    def test_create_workspace_comment(self):
        citation = self.test_create_citation()
        data = citation.data
        citation_id = data.get("id")

        self.client.force_authenticate(
            self.authenticated_user, organization=self.authenticated_user.organization
        )
        response = self.client.post(
            f"/api/citation/{citation_id}/comments/create_rh_comment/",
            {
                "comment_content_json": {"ops": [{"insert": "test"}]},
                "thread_type": "GENERIC_COMMENT",
                "privacy_type": "WORKSPACE",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response, citation

    def test_random_user_cant_view_private_comment(self):
        private_comment, citation = self.test_create_private_comment()
        citation_id = citation.data.get("id")
        private_comment_id = private_comment.data.get("id")
        self.client.force_authenticate(self.random_user)

        response_1 = self.client.get(
            f"/api/citation/{citation_id}/comments/{private_comment_id}/"
        )
        response_2 = self.client.get(f"/api/citation/{citation_id}/comments/")
        self.assertEqual(response_1.status_code, 404)
        self.assertEqual(response_2.data.get("count", None), 0)

    def test_random_user_cant_view_workspace_comment(self):
        workspace_comment, citation = self.test_create_workspace_comment()
        citation_id = citation.data.get("id")
        workspace_comment_id = workspace_comment.data.get("id")
        self.client.force_authenticate(self.random_user)

        response_1 = self.client.get(
            f"/api/citation/{citation_id}/comments/{workspace_comment_id}/"
        )
        response_2 = self.client.get(f"/api/citation/{citation_id}/comments/")
        self.assertEqual(response_1.status_code, 404)
        self.assertEqual(response_2.data.get("count", None), 0)

    def test_org_user_can_view_workspace_comment(self):
        Permission.objects.create(
            access_type="ADMIN",
            source=self.authenticated_user.organization,
            user=self.organization_user,
        )
        workspace_comment, citation = self.test_create_workspace_comment()
        workspace_comment_id = workspace_comment.data.get("id")
        citation_id = citation.data.get("id")

        self.client.force_authenticate(
            self.organization_user, organization=self.authenticated_user.organization
        )
        response_1 = self.client.get(
            f"/api/citation/{citation_id}/comments/{workspace_comment_id}/?privacy_type=WORKSPACE"
        )
        response_2 = self.client.get(
            f"/api/citation/{citation_id}/comments/?privacy_type=WORKSPACE"
        )
        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_2.data.get("count", None), 1)
