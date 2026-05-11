from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from user.tests.helpers import create_random_authenticated_user


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
        self.url = "/api/research_ai/expert-finder/searches/{}/".format(self.search.id)

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
            "/api/research_ai/expert-finder/searches/{}/".format(search.id)
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
        response = self.client.get("/api/research_ai/expert-finder/searches/abc/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_has_experts_relational_payload(self):
        from research_ai.models import SearchExpert

        ex = Expert.objects.create(
            email="d@v.edu",
            first_name="D",
            last_name="Vee",
            academic_title="Professor",
        )
        SearchExpert.objects.create(expert_search=self.search, expert=ex, position=0)
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.json()
        self.assertNotIn("expert_results", data)
        self.assertIn("experts", data)
        self.assertEqual(len(data["experts"]), 1)
        self.assertEqual(data["experts"][0]["email"], "d@v.edu")
        self.assertEqual(data["experts"][0]["id"], ex.id)

    def test_detail_returns_excluded_search_ids(self):
        search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="With exclusions",
            status=ExpertSearch.Status.COMPLETED,
            expert_count=0,
            excluded_search_ids=[7],
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.get(
            "/api/research_ai/expert-finder/searches/{}/".format(search.id)
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.json()["excluded_search_ids"], [7])


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

    def test_invited_returns_chain_ids_and_user_payload(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Invited with data",
            paper_publish_date="2021-01-01",
        )
        ud_id = paper.unified_document_id

        search = ExpertSearch.objects.create(
            created_by=self.moderator,
            unified_document_id=ud_id,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        ex = Expert.objects.create(
            email="invited-view@edu",
            first_name="Inv",
            last_name="Expert",
            registered_user=self.moderator,
        )
        SearchExpert.objects.create(expert_search=search, expert=ex, position=0)
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search,
            expert_email="invited-view@edu",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/documents/{}/invited/".format(ud_id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total_count"], 1)
        self.assertEqual(len(data["invited"]), 1)
        item = data["invited"][0]
        self.assertNotIn("expert", item)
        self.assertNotIn("author", item)
        self.assertIn("user", item)
        self.assertEqual(item["user"]["user_id"], self.moderator.id)
        self.assertIsInstance(item["user"]["author"], (dict, type(None)))
        self.assertIn("expert_search_id", item)
        self.assertIn("generated_email_id", item)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ExpertSearchListCreateViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("v2mod", moderator=True)
        self.user = create_random_authenticated_user("v2usr", moderator=False)
        self.base = "/api/research_ai/expert-finder/searches/"

    def test_create_requires_auth(self):
        r = self.client.post(self.base, {"query": "x"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_requires_moderator(self):
        self.client.force_authenticate(self.user)
        r = self.client.post(self.base, {"query": "x"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    @patch("research_ai.views.expert_finder_views.get_document_content")
    @patch("research_ai.views.expert_finder_views.run_expert_finder_search.delay")
    def test_create_enqueues_v2_task(self, mock_delay, mock_get_document_content):
        from paper.tests.helpers import create_paper

        mock_get_document_content.return_value = ("abstract text", "abstract")
        paper = create_paper(
            title="V2 Topic Paper",
            paper_publish_date="2021-06-01",
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.base,
            {
                "unified_document_id": paper.unified_document_id,
                "input_type": "abstract",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        data = r.json()
        self.assertIn("search_id", data)
        mock_delay.assert_called_once()
        search = ExpertSearch.objects.get(id=data["search_id"])
        self.assertEqual(search.excluded_search_ids, [])
        self.assertEqual(search.unified_document_id, paper.unified_document_id)

    @patch("research_ai.views.expert_finder_views.get_document_content")
    @patch("research_ai.views.expert_finder_views.run_expert_finder_search.delay")
    def test_create_persists_excluded_search_ids(
        self, mock_delay, mock_get_document_content
    ):
        from paper.tests.helpers import create_paper

        mock_get_document_content.return_value = ("abstract text", "abstract")
        paper = create_paper(
            title="V2 Exclude Paper",
            paper_publish_date="2020-01-01",
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.base,
            {
                "unified_document_id": paper.unified_document_id,
                "input_type": "abstract",
                "excluded_search_ids": [3, 3, 5],
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        search = ExpertSearch.objects.get(id=r.json()["search_id"])
        self.assertEqual(search.excluded_search_ids, [3, 5])
        _, kwargs = mock_delay.call_args
        self.assertEqual(kwargs.get("excluded_search_ids"), [3, 5])

    def test_list_requires_auth(self):
        r = self.client.get(self.base)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_v2_shape_without_expert_names(self):
        from research_ai.models import Expert, SearchExpert

        es = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="L",
            status=ExpertSearch.Status.COMPLETED,
            expert_count=1,
        )
        ex = Expert.objects.create(
            email="p@q.edu",
            honorific="Dr",
            first_name="Pat",
            last_name="Lee",
        )
        SearchExpert.objects.create(expert_search=es, expert=ex, position=0)
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.base)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        body = r.json()
        self.assertEqual(body["total"], 1)
        row = body["searches"][0]
        self.assertEqual(row["search_id"], es.id)
        self.assertIn("excluded_search_ids", row)
        self.assertNotIn("expert_names", row)
        self.assertEqual(row["expert_count"], 1)

    @patch("research_ai.views.expert_finder_views.get_document_content")
    @patch("research_ai.views.expert_finder_views.run_expert_finder_search.delay")
    def test_create_autofills_name_from_paper_title(
        self, mock_delay, mock_get_document_content
    ):
        mock_get_document_content.return_value = ("abstract text", "abstract")
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Autofill Name Paper",
            paper_publish_date="2021-06-01",
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.base,
            {
                "unified_document_id": paper.unified_document_id,
                "input_type": "abstract",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        search = ExpertSearch.objects.get(id=r.json()["search_id"])
        self.assertEqual(search.name, "Autofill Name Paper")


class ExpertPatchViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("v2pmod", moderator=True)
        self.user = create_random_authenticated_user("v2pusr", moderator=False)
        self.expert = Expert.objects.create(
            email="before@uni.edu",
            first_name="Before",
            last_name="Name",
            sources=[{"text": "Old", "url": "https://old.example"}],
        )
        self.url = f"/api/research_ai/expert-finder/experts/{self.expert.id}/"

    def test_patch_requires_moderator(self):
        self.client.force_authenticate(self.user)
        r = self.client.patch(self.url, {"first_name": "After"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_updates_expert(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.patch(
            self.url,
            {
                "first_name": "  Ada  ",
                "last_name": "  Lovelace ",
                "email": " ADA@UNI.EDU ",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        body = r.json()
        self.assertEqual(body["id"], self.expert.id)
        self.assertEqual(body["first_name"], "Ada")
        self.assertEqual(body["last_name"], "Lovelace")
        self.assertEqual(body["email"], "ada@uni.edu")
        self.assertEqual(
            body["sources"],
            [{"text": "Old", "url": "https://old.example"}],
        )
        self.expert.refresh_from_db()
        self.assertEqual(self.expert.email, "ada@uni.edu")
        self.assertEqual(
            self.expert.sources,
            [{"text": "Old", "url": "https://old.example"}],
        )

    def test_patch_not_found_returns_404(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.patch(
            "/api/research_ai/expert-finder/experts/999999/",
            {"first_name": "X"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
