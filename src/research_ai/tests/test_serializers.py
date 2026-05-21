from unittest.mock import MagicMock, PropertyMock

from django.test import TestCase

from research_ai.constants import ExpertiseLevel, Gender, Region
from research_ai.models import (
    EmailTemplate,
    Expert,
    ExpertSearch,
    GeneratedEmail,
    SearchExpert,
)
from research_ai.serializers import (
    ADDITIONAL_CONTEXT_MAX_LENGTH,
    EmailTemplateSerializer,
    ExpertSearchConfigSerializer,
    ExpertSearchCreateSerializer,
    ExpertSearchDetailSerializer,
    ExpertSearchListItemSerializer,
    ExpertUpdateSerializer,
    GeneratedEmailSerializer,
    ResearchAIAuthorSerializer,
    _get_created_by_payload,
)
from user.tests.helpers import create_random_authenticated_user


class ExpertSearchConfigSerializerTests(TestCase):
    def test_default_values(self):
        ser = ExpertSearchConfigSerializer(data={})
        self.assertTrue(ser.is_valid())
        data = ser.validated_data
        self.assertEqual(data["expert_count"], 10)
        self.assertEqual(data["expertise_level"], [ExpertiseLevel.ALL_LEVELS])
        self.assertEqual(data["region"], Region.ALL_REGIONS)
        self.assertEqual(data["gender"], Gender.ALL_GENDERS)

    def test_expertise_level_empty_array_defaults_to_all_levels(self):
        ser = ExpertSearchConfigSerializer(data={"expertise_level": []})
        self.assertTrue(ser.is_valid())
        self.assertEqual(
            ser.validated_data["expertise_level"], [ExpertiseLevel.ALL_LEVELS]
        )

    def test_expertise_level_array(self):
        ser = ExpertSearchConfigSerializer(
            data={
                "expertise_level": [
                    ExpertiseLevel.EARLY_CAREER,
                    ExpertiseLevel.MID_CAREER,
                ]
            }
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(
            ser.validated_data["expertise_level"],
            [ExpertiseLevel.EARLY_CAREER, ExpertiseLevel.MID_CAREER],
        )

    def test_expertise_level_list(self):
        """expertise_level accepts a list of choices."""
        ser = ExpertSearchConfigSerializer(
            data={"expertise_level": [ExpertiseLevel.TOP_EXPERT]}
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(
            ser.validated_data["expertise_level"], [ExpertiseLevel.TOP_EXPERT]
        )

    def test_config_snake_case(self):
        """API uses snake_case only (expert_count, expertise_level, gender)."""
        ser = ExpertSearchConfigSerializer(
            data={
                "expert_count": 15,
                "expertise_level": [ExpertiseLevel.EARLY_CAREER],
                "gender": Gender.FEMALE,
            }
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["expert_count"], 15)
        self.assertEqual(
            ser.validated_data["expertise_level"], [ExpertiseLevel.EARLY_CAREER]
        )
        self.assertEqual(ser.validated_data["gender"], Gender.FEMALE)

    def test_expert_count_bounds(self):
        ser = ExpertSearchConfigSerializer(data={"expert_count": 5})
        self.assertTrue(ser.is_valid())
        ser = ExpertSearchConfigSerializer(data={"expert_count": 100})
        self.assertTrue(ser.is_valid())
        ser = ExpertSearchConfigSerializer(data={"expert_count": 4})
        self.assertFalse(ser.is_valid())
        ser = ExpertSearchConfigSerializer(data={"expert_count": 101})
        self.assertFalse(ser.is_valid())


class ExpertSearchCreateSerializerTests(TestCase):
    def test_valid_document_and_dedupes_excluded_search_ids(self):
        ser = ExpertSearchCreateSerializer(
            data={
                "unified_document_id": 1,
                "input_type": "abstract",
                "excluded_search_ids": [1, 2, 1],
            }
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["excluded_search_ids"], [1, 2])

    def test_requires_input_type_with_unified_document(self):
        ser = ExpertSearchCreateSerializer(data={"unified_document_id": 1})
        self.assertFalse(ser.is_valid())
        self.assertIn("input_type", ser.errors)

    def test_requires_unified_document_id(self):
        ser = ExpertSearchCreateSerializer(data={"input_type": "abstract"})
        self.assertFalse(ser.is_valid())
        self.assertIn("unified_document_id", ser.errors)

    def test_additional_context_max_length(self):
        ser = ExpertSearchCreateSerializer(
            data={
                "unified_document_id": 1,
                "input_type": "abstract",
                "additional_context": "x" * (ADDITIONAL_CONTEXT_MAX_LENGTH + 1),
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("additional_context", ser.errors)


class ExpertSearchDetailSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("v2ser")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="V2",
            status=ExpertSearch.Status.COMPLETED,
            excluded_search_ids=[9],
        )
        ex = Expert.objects.create(email="v2@x.edu", first_name="Vi", last_name="Two")
        SearchExpert.objects.create(expert_search=self.search, expert=ex, position=0)

    def test_detail_has_experts_array(self):
        ser = ExpertSearchDetailSerializer(self.search)
        self.assertNotIn("expert_results", ser.data)
        self.assertEqual(len(ser.data["experts"]), 1)
        self.assertEqual(ser.data["experts"][0]["email"], "v2@x.edu")
        self.assertIn("last_email_sent_at", ser.data["experts"][0])
        self.assertIsNone(ser.data["experts"][0]["last_email_sent_at"])

    def test_manually_added_experts_returned_first(self):
        # Existing setUp seeded a non-manual expert at position 0.
        auto_later = Expert.objects.create(
            email="auto2@x.edu", first_name="Auto", last_name="Later"
        )
        SearchExpert.objects.create(
            expert_search=self.search, expert=auto_later, position=1
        )
        manual_a = Expert.objects.create(
            email="manual_a@x.edu",
            first_name="Manual",
            last_name="A",
            is_manually_added=True,
        )
        SearchExpert.objects.create(
            expert_search=self.search, expert=manual_a, position=2
        )
        manual_b = Expert.objects.create(
            email="manual_b@x.edu",
            first_name="Manual",
            last_name="B",
            is_manually_added=True,
        )
        SearchExpert.objects.create(
            expert_search=self.search, expert=manual_b, position=3
        )

        ser = ExpertSearchDetailSerializer(self.search)
        emails = [e["email"] for e in ser.data["experts"]]

        # Manual experts first (in original position order), then non-manual
        # experts (also in original position order).
        self.assertEqual(
            emails,
            ["manual_a@x.edu", "manual_b@x.edu", "v2@x.edu", "auto2@x.edu"],
        )


class ExpertUpdateSerializerTests(TestCase):
    def setUp(self):
        self.expert = Expert.objects.create(
            email="old@uni.edu",
            first_name="Old",
        )

    def test_normalizes_email_and_preserves_sources(self):
        self.expert.sources = [{"text": "Keep", "url": "https://keep.example"}]
        self.expert.save(update_fields=["sources"])
        ser = ExpertUpdateSerializer(
            self.expert,
            data={
                "email": " NEW@uni.edu ",
                "first_name": "  New ",
            },
            partial=True,
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        updated = ser.save()
        self.assertEqual(updated.email, "new@uni.edu")
        self.assertEqual(updated.first_name, "New")
        self.assertEqual(
            updated.sources, [{"text": "Keep", "url": "https://keep.example"}]
        )


class ExpertSearchDetailSerializerWorkTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("ser")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Test",
            name="Test search",
            status=ExpertSearch.Status.COMPLETED,
            report_pdf_url="https://example.com/a.pdf",
            report_csv_url="https://example.com/a.csv",
        )

    def test_serializer_includes_name(self):
        ser = ExpertSearchDetailSerializer(self.search)
        self.assertEqual(ser.data["name"], "Test search")

    def test_serializer_includes_additional_context(self):
        self.search.additional_context = "User notes"
        self.search.save(update_fields=["additional_context"])
        ser = ExpertSearchDetailSerializer(self.search)
        self.assertEqual(ser.data["additional_context"], "User notes")

    def test_get_report_urls(self):
        ser = ExpertSearchDetailSerializer(self.search)
        self.assertEqual(
            ser.data["report_urls"],
            {"pdf": "https://example.com/a.pdf", "csv": "https://example.com/a.csv"},
        )

    def test_get_report_urls_none_when_empty(self):
        self.search.report_pdf_url = ""
        self.search.report_csv_url = ""
        self.search.save()
        ser = ExpertSearchDetailSerializer(self.search)
        self.assertIsNone(ser.data["report_urls"])

    def test_created_by_payload_has_user_id_and_author_key(self):
        ser = ExpertSearchDetailSerializer(self.search)
        created_by = ser.data["created_by"]
        self.assertEqual(created_by["user_id"], self.user.id)
        self.assertIn("author", created_by)
        if created_by["author"] is not None:
            self.assertIn("id", created_by["author"])

    def test_work_is_none_when_no_unified_document(self):
        ser = ExpertSearchDetailSerializer(self.search)
        self.assertIsNone(self.search.unified_document_id)
        self.assertIsNone(ser.data["work"])

    def test_work_resolves_paper_when_unified_document_is_paper(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Expert Search Paper Title",
            paper_publish_date="2020-01-01",
        )
        search_with_paper = ExpertSearch.objects.create(
            created_by=self.user,
            unified_document=paper.unified_document,
            query="From paper",
            status=ExpertSearch.Status.COMPLETED,
        )
        ser = ExpertSearchDetailSerializer(search_with_paper)
        work = ser.data["work"]
        self.assertIsNotNone(work)
        self.assertEqual(work["type"], "paper")
        self.assertEqual(work["id"], paper.id)
        self.assertEqual(work["unified_document_id"], paper.unified_document_id)
        self.assertIn("Expert Search Paper Title", work["title"])
        self.assertEqual(work["slug"], paper.slug)
        self.assertIn("file", work)
        self.assertIn("pdf_url", work)


class ExpertSearchListItemSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("list")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="List test",
            status=ExpertSearch.Status.COMPLETED,
            excluded_search_ids=[3],
        )

    def test_list_item_fields(self):
        ser = ExpertSearchListItemSerializer(self.search)
        self.assertEqual(ser.data["search_id"], self.search.id)
        self.assertEqual(ser.data["query"], "List test")
        self.assertEqual(ser.data["excluded_search_ids"], [3])

    def test_created_by_payload_has_user_id_and_author_key(self):
        ser = ExpertSearchListItemSerializer(self.search)
        created_by = ser.data["created_by"]
        self.assertEqual(created_by["user_id"], self.user.id)
        self.assertIn("author", created_by)


class GeneratedEmailSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("email_ser")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
        )

    def test_serialize_generated_email(self):
        email = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.search,
            expert_name="Dr. Foo",
            expert_email="foo@bar.com",
            email_subject="Hi",
            email_body="Body",
        )
        ser = GeneratedEmailSerializer(email)
        self.assertEqual(ser.data["expert_name"], "Dr. Foo")
        self.assertEqual(ser.data["expert_email"], "foo@bar.com")

    def test_created_by_payload_has_user_id_and_author_key(self):
        email = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.search,
            expert_name="Dr. Foo",
            expert_email="foo@bar.com",
        )
        ser = GeneratedEmailSerializer(email)
        created_by = ser.data["created_by"]
        self.assertEqual(created_by["user_id"], self.user.id)
        self.assertIn("author", created_by)


class EmailTemplateSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("tmpl_ser")

    def test_created_by_payload_has_user_id_and_author_key(self):
        template = EmailTemplate.objects.create(
            created_by=self.user,
            name="T",
        )
        ser = EmailTemplateSerializer(template)
        created_by = ser.data["created_by"]
        self.assertEqual(created_by["user_id"], self.user.id)
        self.assertIn("author", created_by)


class ResearchAIAuthorSerializerTests(TestCase):
    def setUp(self):
        self.serializer = ResearchAIAuthorSerializer()

    def test_profile_image_returns_url_when_set(self):
        author = MagicMock()
        author.profile_image = MagicMock()
        author.profile_image.name = "avatars/x.png"
        author.profile_image.url = "https://example.com/media/avatars/x.png"
        self.assertEqual(
            self.serializer.get_profile_image(author),
            "https://example.com/media/avatars/x.png",
        )

    def test_profile_image_returns_none_when_missing_name(self):
        author = MagicMock()
        author.profile_image = MagicMock()
        author.profile_image.name = ""
        self.assertIsNone(self.serializer.get_profile_image(author))

    def test_profile_image_returns_none_when_url_raises(self):
        author = MagicMock()
        img = MagicMock()
        img.name = "a.png"
        type(img).url = PropertyMock(side_effect=OSError("storage error"))
        author.profile_image = img
        self.assertIsNone(self.serializer.get_profile_image(author))


class GetCreatedByPayloadTests(TestCase):
    def test_author_none_when_user_has_no_author_profile(self):
        obj = MagicMock()
        user = MagicMock()
        user.id = 42
        user.author_profile = None
        obj.created_by = user
        payload = _get_created_by_payload(obj)
        self.assertEqual(payload["user_id"], 42)
        self.assertIsNone(payload["author"])
        user.id = 42
        user.author_profile = None
        obj.created_by = user
        payload = _get_created_by_payload(obj)
        self.assertEqual(payload["user_id"], 42)
        self.assertIsNone(payload["author"])
