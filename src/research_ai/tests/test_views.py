from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_hub_editor, create_random_authenticated_user


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


class InvitedExpertOverviewViewTests(APITestCase):
    URL = "/api/research_ai/expert-finder/overview/"

    OVERVIEW_FIELDS = (
        "experts_total",
        "experts_signed_up",
        "emails_generated",
        "emails_sent",
        "emails_bounced",
        "emails_opened",
        "proposals_opened",
    )

    def setUp(self):
        self.moderator = create_random_authenticated_user(
            "mod_overview", moderator=True
        )
        self.user = create_random_authenticated_user("user_overview", moderator=False)
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_overview_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_overview_nonexistent_document_returns_empty_metrics(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.URL, {"unified_document_id": 999999})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["experts_total"], 0)
        self.assertEqual(data["summary"]["searches_total"], 0)

    def test_overview_aggregates_counts_for_document(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Overview paper",
            paper_publish_date="2021-01-01",
        )
        ud_id = paper.unified_document_id

        search = ExpertSearch.objects.create(
            created_by=self.moderator,
            unified_document_id=ud_id,
            query="Overview",
            status=ExpertSearch.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        signed_up_expert = Expert.objects.create(
            email="signedup@example.com",
            first_name="Signed",
            last_name="Up",
            registered_user=self.moderator,
        )
        not_signed_up_expert = Expert.objects.create(
            email="invited@example.com",
            first_name="Inv",
            last_name="Expert",
        )
        SearchExpert.objects.create(
            expert_search=search, expert=signed_up_expert, position=0
        )
        SearchExpert.objects.create(
            expert_search=search, expert=not_signed_up_expert, position=1
        )
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search,
            expert_email="signedup@example.com",
            status=GeneratedEmail.Status.SENT,
            opened_at=timezone.now(),
            open_count=2,
        )
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search,
            expert_email="invited@example.com",
            status=GeneratedEmail.Status.BOUNCED,
            bounced_at=timezone.now(),
        )
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search,
            expert_email="other@example.com",
            status=GeneratedEmail.Status.DRAFT,
        )
        create_post(created_by=self.moderator, document_type=PREREGISTRATION)

        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.URL, {"unified_document_id": ud_id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["experts_total"], 2)
        self.assertEqual(data["experts_signed_up"], 1)
        self.assertEqual(data["emails_generated"], 3)
        self.assertEqual(data["emails_sent"], 1)
        self.assertEqual(data["emails_bounced"], 1)
        self.assertEqual(data["emails_opened"], 1)
        self.assertEqual(data["proposals_opened"], 1)
        self.assertIn("cached_at", data["meta"])
        self.assertIn("filters", data["meta"])
        self.assertIn("summary", data)
        self.assertEqual(data["summary"]["searches_total"], 1)
        self.assertEqual(data["summary"]["searches_completed"], 1)

    def test_overview_filters_by_date_range(self):
        old_search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Old",
            status=ExpertSearch.Status.COMPLETED,
        )
        ExpertSearch.objects.filter(pk=old_search.pk).update(
            created_date=timezone.now() - timedelta(days=30)
        )
        recent_search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Recent",
            status=ExpertSearch.Status.COMPLETED,
        )
        old_expert = Expert.objects.create(email="old@example.com")
        recent_expert = Expert.objects.create(email="recent@example.com")
        SearchExpert.objects.create(
            expert_search=old_search, expert=old_expert, position=0
        )
        SearchExpert.objects.create(
            expert_search=recent_search, expert=recent_expert, position=0
        )
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=old_search,
            expert_email="old@example.com",
            status=GeneratedEmail.Status.SENT,
        )
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=recent_search,
            expert_email="recent@example.com",
            status=GeneratedEmail.Status.SENT,
        )

        self.client.force_authenticate(self.moderator)
        today = timezone.localdate()
        start = (today - timedelta(days=2)).isoformat()
        response = self.client.get(self.URL, {"start": start})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["experts_total"], 1)
        self.assertEqual(data["emails_generated"], 1)
        self.assertEqual(data["emails_sent"], 1)

    def test_overview_invalid_date_range_returns_400(self):
        self.client.force_authenticate(self.moderator)
        today = timezone.localdate()
        response = self.client.get(
            self.URL,
            {
                "start": today.isoformat(),
                "end": (today - timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class InvitedExpertEditorsOverviewViewTests(APITestCase):
    URL = "/api/research_ai/expert-finder/editors-overview/"

    def setUp(self):
        self.moderator = create_random_authenticated_user("mod_editors", moderator=True)
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_editors_overview_ranks_by_experts_total(self):
        editor_a, _ = create_hub_editor("stats_editor_a", "stats_hub_a")
        editor_b, _ = create_hub_editor("stats_editor_b", "stats_hub_b")
        search_a = ExpertSearch.objects.create(
            created_by=editor_a,
            query="A",
            status=ExpertSearch.Status.COMPLETED,
        )
        search_b = ExpertSearch.objects.create(
            created_by=editor_b,
            query="B",
            status=ExpertSearch.Status.COMPLETED,
        )
        for i in range(3):
            expert = Expert.objects.create(email=f"ed_a_{i}@example.com")
            SearchExpert.objects.create(
                expert_search=search_a, expert=expert, position=i
            )
        expert_b = Expert.objects.create(email="ed_b_0@example.com")
        SearchExpert.objects.create(expert_search=search_b, expert=expert_b, position=0)

        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.URL, {"limit": 5})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["items"][0]["experts_total"], 3)
        self.assertEqual(data["items"][0]["editor"]["user_id"], editor_a.id)
        self.assertEqual(data["items"][0]["proposals_outreach_count"], 0)
        self.assertEqual(data["items"][0]["emails_sent_by_proposal"], {})

    def test_editors_invalid_sort_by_returns_400(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.URL, {"sort_by": "invalid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


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
