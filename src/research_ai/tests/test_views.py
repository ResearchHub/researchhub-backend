from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from user.tests.helpers import create_random_authenticated_user


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ExpertSearchCreateViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.url = "/api/research_ai/expert-finder/search/"

    def test_create_requires_authentication(self):
        response = self.client.post(self.url, {"query": "ML"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, {"query": "ML"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("research_ai.tasks.process_expert_search_task.delay")
    def test_create_with_query_returns_201(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url, {"query": "Machine learning"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn("search_id", data)
        search = ExpertSearch.objects.get(id=data["search_id"])
        self.assertEqual(search.created_by, self.moderator)
        mock_delay.assert_called_once()

    @patch("research_ai.views.expert_finder_views.get_document_content")
    @patch("research_ai.tasks.process_expert_search_task.delay")
    def test_create_with_unified_document_autofills_name(
        self, mock_delay, mock_get_document_content
    ):
        mock_get_document_content.return_value = ("abstract text", "abstract")
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Autofill Name Paper",
            paper_publish_date="2021-06-01",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "unified_document_id": paper.unified_document_id,
                "input_type": "abstract",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        search = ExpertSearch.objects.get(id=response.json()["search_id"])
        self.assertEqual(search.name, "Autofill Name Paper")

    @patch("research_ai.tasks.process_expert_search_task.delay")
    def test_create_with_name_uses_provided_name(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"query": "Custom query", "name": "My custom search name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        search = ExpertSearch.objects.get(id=response.json()["search_id"])
        self.assertEqual(search.name, "My custom search name")

    def test_create_without_query_returns_400(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_unified_document_requires_input_type(self):
        """Creating a search with a document requires input_type (e.g. abstract or pdf)."""
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Paper",
            paper_publish_date="2021-06-01",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"unified_document_id": paper.unified_document_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("input_type", response.json())

    def test_create_unified_document_not_found_returns_404(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"unified_document_id": 999999, "input_type": "abstract"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("research_ai.tasks.ExpertFinderService")
    def test_when_expert_finder_returns_no_table_search_is_failed_with_error_message(
        self, mock_service_class
    ):
        """When service returns FAILED (no parseable table), task saves status=FAILED and error_message."""
        mock_instance = mock_service_class.return_value
        mock_instance.process_expert_search.return_value = {
            "search_id": "999",
            "status": ExpertSearch.Status.FAILED,
            "query": "Placeholder RFP",
            "config": {},
            "report_urls": {},
            "expert_count": 0,
            "llm_model": "test-model",
            "error_message": "I cannot proceed. The input contains only placeholder text.",
            "current_step": "No expert recommendations table returned by model",
        }
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url, {"query": "Placeholder RFP"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        search_id = response.json()["search_id"]
        search = ExpertSearch.objects.get(id=search_id)
        self.assertEqual(search.status, ExpertSearch.Status.FAILED)
        self.assertEqual(search.expert_count, 0)
        self.assertEqual(search.search_experts.count(), 0)
        self.assertIn("placeholder text", search.error_message)


class ExpertSearchDetailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod2", moderator=True)
        self.other = create_random_authenticated_user("other", moderator=True)
        self.search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Detail test",
            status=ExpertSearch.Status.COMPLETED,
            expert_count=2,
        )
        self.url = "/api/research_ai/expert-finder/search/{}/".format(self.search.id)

    def test_get_own_search_returns_200(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["search_id"], self.search.id)

    def test_get_detail_returns_work_when_unified_document(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Detail Work Paper",
            paper_publish_date="2020-01-01",
        )
        search = ExpertSearch.objects.create(
            created_by=self.moderator,
            unified_document=paper.unified_document,
            query="From paper",
            status=ExpertSearch.Status.COMPLETED,
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/search/{}/".format(search.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("work", data)
        self.assertIsNotNone(data["work"])
        self.assertEqual(data["work"]["type"], "paper")
        self.assertEqual(data["work"]["id"], paper.id)
        self.assertIn("Detail Work Paper", data["work"]["title"])

    def test_get_other_user_search_returns_200_shared(self):
        """Searches are shared: any editor/moderator can get any search."""
        self.client.force_authenticate(self.other)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["search_id"], self.search.id)

    def test_get_non_integer_search_id_returns_404(self):
        """Non-integer search_id does not match URL pattern; Django returns 404."""
        self.client.force_authenticate(self.moderator)
        response = self.client.get("/api/research_ai/expert-finder/search/abc/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ExpertSearchListViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod3", moderator=True)
        self.url = "/api/research_ai/expert-finder/searches/"

    def test_list_returns_own_searches(self):
        ExpertSearch.objects.create(
            created_by=self.moderator,
            query="First",
            status=ExpertSearch.Status.COMPLETED,
        )
        ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Second",
            status=ExpertSearch.Status.PENDING,
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["searches"]), 2)


class ExpertSearchProgressStreamViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod4", moderator=True)
        self.search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Stream test",
            status=ExpertSearch.Status.PENDING,
        )
        self.url = "/api/research_ai/expert-finder/progress/{}/".format(self.search.id)

    def test_progress_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_progress_returns_sse_stream(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/event-stream", response.get("Content-Type", ""))


class ExpertSearchWorkViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod_work", moderator=True)
        self.user = create_random_authenticated_user("user_work", moderator=False)

    def test_work_requires_authentication(self):
        response = self.client.get("/api/research_ai/expert-finder/work/1/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_work_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/research_ai/expert-finder/work/1/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_work_unified_document_not_found_returns_404(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get("/api/research_ai/expert-finder/work/999999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json().get("detail"), "Unified document not found.")

    def test_work_returns_paper_when_unified_document_is_paper(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Work Endpoint Paper",
            paper_publish_date="2021-01-01",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/work/{}/".format(paper.unified_document_id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("work", data)
        self.assertIsNotNone(data["work"])
        self.assertEqual(data["work"]["type"], "paper")
        self.assertEqual(data["work"]["unified_document_id"], paper.unified_document_id)
        self.assertIn("Work Endpoint Paper", data["work"]["title"])

    def test_work_returns_post_when_unified_document_is_post(self):
        from researchhub_document.helpers import create_post

        post = create_post(
            title="Work Endpoint Post",
            renderable_text="Post body",
            created_by=self.moderator,
            document_type="DISCUSSION",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/work/{}/".format(post.unified_document_id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("work", data)
        self.assertIsNotNone(data["work"])
        self.assertEqual(data["work"]["type"], "post")
        self.assertEqual(data["work"]["unified_document_id"], post.unified_document_id)
        self.assertIn("Work Endpoint Post", data["work"]["title"])

    @patch("research_ai.views.expert_finder_views.resolve_work_for_unified_document")
    def test_work_returns_null_when_resolution_fails(self, mock_resolve):
        from paper.tests.helpers import create_paper

        paper = create_paper(title="No Work")
        mock_resolve.return_value = None
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/work/{}/".format(paper.unified_document_id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("work", data)
        self.assertIsNone(data["work"])


class InvitedExpertsDocumentViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod_inv", moderator=True)
        self.user = create_random_authenticated_user("user_inv", moderator=False)

    def test_invited_requires_authentication(self):
        response = self.client.get(
            "/api/research_ai/expert-finder/documents/1/invited/"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invited_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(
            "/api/research_ai/expert-finder/documents/1/invited/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invited_nonexistent_document_returns_404(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/documents/999999/invited/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.json().get("detail"),
            "Unified document not found.",
        )

    def test_invited_valid_document_returns_200_and_structure(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Invited endpoint paper",
            paper_publish_date="2021-01-01",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/documents/{}/invited/".format(
                paper.unified_document_id
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("unified_document_id", data)
        self.assertEqual(data["unified_document_id"], paper.unified_document_id)
        self.assertIn("invited", data)
        self.assertIsInstance(data["invited"], list)
        self.assertIn("total_count", data)
        self.assertEqual(data["total_count"], 0)
        self.assertEqual(len(data["invited"]), 0)

    def test_invited_returns_invited_with_author_and_chain_ids(self):
        from paper.tests.helpers import create_paper
        from researchhub_document.models import ResearchhubUnifiedDocument

        paper = create_paper(
            title="Invited with data",
            paper_publish_date="2021-01-01",
        )
        ud = ResearchhubUnifiedDocument.objects.get(id=paper.unified_document_id)
        creator = create_random_authenticated_user("inv_es_creator")
        search = ExpertSearch.objects.create(
            created_by=creator,
            unified_document=ud,
            query="abstract text",
            input_type=ExpertSearch.InputType.ABSTRACT,
            status=ExpertSearch.Status.COMPLETED,
        )
        expert = Expert.objects.create(
            email=self.moderator.email,
            first_name="Mod",
            last_name="Invitee",
            registered_user=self.moderator,
        )
        SearchExpert.objects.create(expert_search=search, expert=expert, position=0)
        ge = GeneratedEmail.objects.create(
            created_by=creator,
            expert_search=search,
            expert_email=self.moderator.email,
            expert_name="Mod",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/documents/{}/invited/".format(
                paper.unified_document_id
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total_count"], 1)
        self.assertEqual(len(data["invited"]), 1)
        item = data["invited"][0]
        self.assertIn("author", item)
        self.assertEqual(item["expert_search_id"], search.id)
        self.assertEqual(item["generated_email_id"], ge.id)
