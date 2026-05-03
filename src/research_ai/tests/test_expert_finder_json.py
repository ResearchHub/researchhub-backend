from django.test import TestCase
from django.utils import timezone

from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.expert_display import ExpertDisplay
from research_ai.services.expert_finder_json import ExpertFinderJson
from research_ai.services.expert_persist import ExpertPersist
from research_ai.utils import trimmed_str
from user.tests.helpers import create_user


class ResearchAIUtilsTests(TestCase):
    def test_trimmed_str(self):
        self.assertEqual(trimmed_str(None), "")
        self.assertEqual(trimmed_str("  a  ", max_len=1), "a")
        self.assertEqual(trimmed_str(42), "42")


class ParseExpertFinderJsonTextTests(TestCase):
    def test_parses_raw_json(self):
        text = '{"experts": [{"email": "a@b.com"}]}'
        self.assertEqual(
            ExpertFinderJson.parse_text(text), {"experts": [{"email": "a@b.com"}]}
        )

    def test_parses_json_in_markdown_fence(self):
        text = 'Here:\n```json\n{"experts": [{"email": "x@y.org"}]}\n```\n'
        self.assertEqual(
            ExpertFinderJson.parse_text(text), {"experts": [{"email": "x@y.org"}]}
        )

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            ExpertFinderJson.parse_text("not json at all")


class ValidateExpertOutputTests(TestCase):
    def test_happy_path_length(self):
        obj = {
            "experts": [
                {
                    "email": "jane@uni.edu",
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "sources": [{"text": "Ref", "url": "https://a.org/x"}],
                }
            ]
        }
        rows = ExpertFinderJson.validate_output(obj)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["email"], "jane@uni.edu")
        self.assertEqual(rows[0]["first_name"], "Jane")
        self.assertEqual(
            rows[0]["sources"], [{"text": "Ref", "url": "https://a.org/x"}]
        )

    def test_drops_bad_rows(self):
        obj = {
            "experts": [
                {"email": "good@x.com", "last_name": "A"},
                "not-a-dict",
                {"last_name": "X"},
                {"email": "bad"},
                {"email": "good@x.com", "last_name": "dup"},
            ]
        }
        rows = ExpertFinderJson.validate_output(obj)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["email"], "good@x.com")
        self.assertEqual(rows[0]["last_name"], "A")

    def test_not_dict_raises(self):
        with self.assertRaises(ValueError):
            ExpertFinderJson.validate_output([])

    def test_missing_experts_raises(self):
        with self.assertRaises(ValueError):
            ExpertFinderJson.validate_output({})

    def test_experts_not_list_raises(self):
        with self.assertRaises(ValueError):
            ExpertFinderJson.validate_output({"experts": None})


class ExpertDisplayTests(TestCase):
    def test_build_name_structured(self):
        n = ExpertDisplay.build_display_name(
            honorific="Dr", first_name="A", last_name="B", name_suffix="PhD"
        )
        self.assertEqual(n, "Dr. A B, PhD")


class ExpertPersistTests(TestCase):
    def setUp(self):
        self.user = create_user(email="u@test.com")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="q",
            status=ExpertSearch.Status.COMPLETED,
        )

    def test_upsert_creates_and_updates(self):
        e1 = ExpertPersist.upsert_from_parsed_dict(
            {
                "email": "A@B.COM",
                "first_name": "Ann",
                "expertise": "ML",
            }
        )
        self.assertEqual(e1.email, "a@b.com")
        e2 = ExpertPersist.upsert_from_parsed_dict(
            {
                "email": "a@b.com",
                "last_name": "B",
            }
        )
        e2.refresh_from_db()
        self.assertEqual(e2.id, e1.id)
        self.assertEqual(e2.first_name, "Ann")
        self.assertEqual(e2.last_name, "B")
        self.assertEqual(e2.expertise, "ML")

    def test_replace_search_experts_for_search(self):
        rows = [
            {
                "email": "a1@u.edu",
                "first_name": "One",
            },
            {
                "email": "a2@u.edu",
                "first_name": "Two",
            },
        ]
        n = ExpertPersist.replace_search_experts_for_search(self.search.id, rows)
        self.assertEqual(n, 2)
        se = list(
            SearchExpert.objects.filter(expert_search_id=self.search.id)
            .order_by("position")
            .select_related("expert")
        )
        self.assertEqual(len(se), 2)
        self.assertEqual(se[0].expert.email, "a1@u.edu")
        self.assertEqual(se[1].position, 1)

        ExpertPersist.replace_search_experts_for_search(
            self.search.id,
            [{"email": "a1@u.edu", "last_name": "Solo"}],
        )
        self.assertEqual(
            SearchExpert.objects.filter(expert_search_id=self.search.id).count(), 1
        )

    def test_mark_expert_last_email_sent_at(self):
        e = ExpertPersist.upsert_from_parsed_dict(
            {
                "email": "m@q.com",
                "first_name": "M",
            }
        )
        t0 = e.last_email_sent_at
        self.assertIsNone(t0)
        before = timezone.now()
        ExpertPersist.mark_last_email_sent_at("M@Q.com")
        e.refresh_from_db()
        self.assertIsNotNone(e.last_email_sent_at)
        self.assertGreaterEqual(e.last_email_sent_at, before)
        ExpertPersist.mark_last_email_sent_at("")
        # no error


class ExpertResultsPayloadTests(TestCase):
    def setUp(self):
        self.user = create_user(email="c@test.com")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="q2",
            status=ExpertSearch.Status.COMPLETED,
        )
        e = Expert.objects.create(
            email="e@d.org",
            first_name="Eve",
            last_name="D",
            academic_title="Assoc Prof",
            sources=[{"text": "t", "url": "u"}],
        )
        SearchExpert.objects.create(
            expert_search=self.search,
            expert=e,
            position=0,
        )
