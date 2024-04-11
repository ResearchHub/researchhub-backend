from django.core.files.uploadedfile import SimpleUploadedFile

from citation.constants import JOURNAL_ARTICLE
from citation.models import CitationEntry
from paper.tests.helpers import create_paper
from researchhub_access_group.models import Permission
from user.tests.helpers import create_random_default_user
from utils.test_helpers import APITestCaseWithOrg


class CitationEntryViewTests(APITestCaseWithOrg):
    def setUp(self):
        self.authenticated_user = create_random_default_user("user1")
        self.random_user = create_random_default_user("random1")
        self.organization_user = create_random_default_user("orguser1")

    def test_get_saved_org_citations(self):
        self.client.force_authenticate(self.organization_user)
        paper = create_paper()

        # Set up organization permissions
        Permission.objects.create(
            access_type="ADMIN",
            source=self.authenticated_user.organization,
            user=self.organization_user,
        )
        self.client.force_authenticate(
            self.organization_user, organization=self.authenticated_user.organization
        )

        # Next, we need to create a project
        response = self.client.post(
            f"/api/citation_project/",
            {
                "children": [],
                "organization": self.authenticated_user.organization.id,
                "collaborators": [],
                "is_public": True,
                "project_name": "TEST",
                "status": "full_access",
            },
        )
        project_id = response.data["id"]

        # Now let's add the paper to the project
        response = self.client.post(
            f"/api/citation_entry/{paper.id}/add_paper_as_citation/",
            {
                "project_id": project_id,
            },
            format="json",
        )

        citation_id = response.data["id"]

        # Finally let's ensure the citation was saved
        response = self.client.get("/api/citation_entry/saved_org_citations/")
        self.assertEqual(response.data[0]["id"], citation_id)

    def test_create_citation(self):
        self.client.force_authenticate(self.authenticated_user)
        response = self.client.post(
            "/api/citation_entry/",
            {
                "fields": {
                    "id": "user_1_JOURNAL_ARTICLE",
                    "DOI": "10.1101/1997.01.01.12345",
                    "URL": "",
                    "ISSN": "",
                    "note": "",
                    "page": "",
                    "type": "article-journal",
                    "issue": "",
                    "title": "Test title",
                    "author": [
                        {"given": "John", "family": "Doe"},
                        {"given": "Alice", "family": "Alice"},
                        {"given": "Bob", "family": "Bob"},
                    ],
                    "issued": {"date-parts": [["2000", "01", "01"]]},
                    "source": "",
                    "volume": "",
                    "archive": "",
                    "abstract": "This is a fake abstract",
                    "language": "",
                    "call-number": "",
                    "title-short": "",
                    "container-title": "Fake title",
                    "archive_location": "",
                    "collection-title": "",
                    "journalAbbreviation": "",
                },
                "citation_type": JOURNAL_ARTICLE,
                "doi": "10.1101/1997.01.01.12345",
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
            f"/api/citationentry/{citation_id}/comments/create_rh_comment/",
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
            f"/api/citationentry/{citation_id}/comments/create_rh_comment/",
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
            f"/api/citationentry/{citation_id}/comments/{private_comment_id}/"
        )
        response_2 = self.client.get(f"/api/citationentry/{citation_id}/comments/")
        self.assertEqual(response_1.status_code, 404)
        self.assertEqual(response_2.data.get("count", None), 0)

    def test_random_user_cant_view_workspace_comment(self):
        workspace_comment, citation = self.test_create_workspace_comment()
        citation_id = citation.data.get("id")
        workspace_comment_id = workspace_comment.data.get("id")
        self.client.force_authenticate(self.random_user)

        response_1 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/{workspace_comment_id}/"
        )
        response_2 = self.client.get(f"/api/citationentry/{citation_id}/comments/")
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
            f"/api/citationentry/{citation_id}/comments/{workspace_comment_id}/?privacy_type=WORKSPACE"
        )
        response_2 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/?privacy_type=WORKSPACE"
        )
        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_2.data.get("count", None), 1)

    def test_change_comment_from_private_to_workspace(self):
        private_comment, citation = self.test_create_private_comment()
        citation_id = citation.data.get("id")
        private_comment_id = private_comment.data.get("id")
        self.client.force_authenticate(
            self.authenticated_user, organization=self.authenticated_user.organization
        )
        response_1 = self.client.patch(
            f"/api/citationentry/{citation_id}/comments/{private_comment_id}/update_comment_permission/",
            {
                "privacy_type": "WORKSPACE",
                "content_type": "citationentry",
                "object_id": private_comment_id,
            },
        )
        self.assertEqual(response_1.status_code, 200)

        self.client.force_authenticate(
            self.organization_user, organization=self.organization_user.organization
        )
        response_2 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/{private_comment_id}/?privacy_type=WORKSPACE"
        )
        self.assertEqual(response_2.status_code, 404)

        Permission.objects.create(
            access_type="ADMIN",
            source=self.authenticated_user.organization,
            user=self.organization_user,
        )
        self.client.force_authenticate(
            self.organization_user, organization=self.authenticated_user.organization
        )
        response_3 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/?privacy_type=WORKSPACE"
        )
        self.assertEqual(response_3.data.get("count", None), 1)

    def test_change_comment_from_workspace_to_private(self):
        workspace_comment, citation = self.test_create_workspace_comment()
        citation_id = citation.data.get("id")
        workspace_comment_id = workspace_comment.data.get("id")
        self.client.force_authenticate(
            self.authenticated_user, organization=self.authenticated_user.organization
        )
        response_1 = self.client.patch(
            f"/api/citationentry/{citation_id}/comments/{workspace_comment_id}/update_comment_permission/",
            {
                "privacy_type": "PRIVATE",
                "content_type": "citationentry",
                "object_id": citation_id,
            },
        )
        self.assertEqual(response_1.status_code, 200)

        self.client.force_authenticate(
            self.organization_user, organization=self.organization_user.organization
        )
        response_2 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/{workspace_comment_id}/?privacy_type=PRIVATE"
        )
        self.assertEqual(response_2.status_code, 404)

        Permission.objects.create(
            access_type="ADMIN",
            source=self.authenticated_user.organization,
            user=self.organization_user,
        )
        self.client.force_authenticate(
            self.organization_user, organization=self.authenticated_user.organization
        )
        response_3 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/?privacy_type=PRIVATE"
        )
        self.assertEqual(response_3.data.get("count", None), 0)

        self.client.force_authenticate(
            self.authenticated_user, organization=self.authenticated_user.organization
        )
        response_4 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/?privacy_type=PRIVATE"
        )
        self.assertEqual(response_4.data.get("count", None), 1)

    def test_change_comment_from_private_to_public(self):
        paper = create_paper()
        private_comment, citation = self.test_create_private_comment()
        citation_id = citation.data.get("id")
        private_comment_id = private_comment.data.get("id")
        self.client.force_authenticate(
            self.authenticated_user, organization=self.authenticated_user.organization
        )
        response_1 = self.client.patch(
            f"/api/citationentry/{citation_id}/comments/{private_comment_id}/update_comment_permission/",
            {
                "privacy_type": "PUBLIC",
                "content_type": "paper",
                "object_id": paper.id,
            },
        )
        self.assertEqual(response_1.status_code, 200)

        self.client.force_authenticate(self.organization_user)
        response_2 = self.client.get(
            f"/api/paper/{paper.id}/comments/{private_comment_id}/"
        )
        self.assertEqual(response_2.status_code, 200)
        return paper, citation, private_comment

    def test_change_comment_from_public_to_private(self):
        (
            paper,
            citation,
            public_comment,
        ) = self.test_change_comment_from_private_to_public()
        paper_id = paper.id
        citation_id = citation.data.get("id")
        public_comment_id = public_comment.data.get("id")
        self.client.force_authenticate(
            self.authenticated_user, organization=self.authenticated_user.organization
        )
        response_1 = self.client.patch(
            f"/api/paper/{paper_id}/comments/{public_comment_id}/update_comment_permission/",
            {
                "privacy_type": "PRIVATE",
                "content_type": "citationentry",
                "object_id": citation_id,
            },
        )
        self.assertEqual(response_1.status_code, 200)

        response_2 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/{public_comment_id}/?privacy_type=PRIVATE"
        )
        self.assertEqual(response_2.status_code, 200)
        response_3 = self.client.get(
            f"/api/citationentry/{citation_id}/comments/?privacy_type=PRIVATE"
        )
        self.assertEqual(response_3.data.get("count", None), 1)


class PaperCitationEntryViewTests(APITestCaseWithOrg):
    def setUp(self):
        self.authenticated_user = create_random_default_user("user1")
        self.random_user = create_random_default_user("random1")
        self.organization_user = create_random_default_user("orguser1")

    def test_add_paper_as_citation(self):
        self.client.force_authenticate(self.authenticated_user)

        paper = create_paper()
        paper.paper_title = "test_add_paper_as_citation"
        paper.save()

        response = self.client.post(
            f"/api/citation_entry/{paper.id}/add_paper_as_citation/",
            {
                "organization": self.authenticated_user.organization.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_add_paper_as_citation_with_pdf_and_closed_access(self):
        self.client.force_authenticate(self.authenticated_user)

        mock_file = SimpleUploadedFile(
            "test.pdf",
            b"These are the contents of the pdf file.",
            content_type="application/pdf",
        )
        paper = create_paper()
        paper.paper_title = "test_add_paper_as_citation_with_pdf_and_closed_access"
        paper.file = mock_file
        paper.pdf_license = "publisher-specific, author-manuscript"  # from https://api.openalex.org/works?group_by=primary_location.license:include_unknown
        paper.save()

        response = self.client.post(
            f"/api/citation_entry/{paper.id}/add_paper_as_citation/",
            {
                "organization": self.authenticated_user.organization.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        paper.refresh_from_db()

        citation = CitationEntry.objects.get(id=response.data["id"])
        self.assertFalse(citation.attachment)
