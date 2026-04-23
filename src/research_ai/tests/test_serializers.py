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
    ExpertSearchListItemSerializer,
    ExpertSearchSerializer,
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
    def test_query_only_valid(self):
        ser = ExpertSearchCreateSerializer(data={"query": "Machine learning"})
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["query"], "Machine learning")
        # input_type is optional when using custom query (no document)

    def test_unified_document_id_only_valid(self):
        ser = ExpertSearchCreateSerializer(
            data={"unified_document_id": 123, "input_type": "abstract"}
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["unified_document_id"], 123)
        self.assertEqual(ser.validated_data["input_type"], "abstract")

    def test_neither_query_nor_document_invalid(self):
        ser = ExpertSearchCreateSerializer(data={})
        self.assertFalse(ser.is_valid())
        ser2 = ExpertSearchCreateSerializer(data={"query": ""})
        self.assertFalse(ser2.is_valid())

    def test_both_query_and_document_invalid(self):
        ser = ExpertSearchCreateSerializer(
            data={"query": "Foo", "unified_document_id": 1}
        )
        self.assertFalse(ser.is_valid())

    def test_excluded_search_ids_deduped(self):
        ser = ExpertSearchCreateSerializer(
            data={"query": "Bar", "excluded_search_ids": [3, 3, 1, 2]},
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["excluded_search_ids"], [3, 1, 2])

    def test_name_optional_accepted(self):
        ser = ExpertSearchCreateSerializer(
            data={"query": "Q", "name": "My expert search"}
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["name"], "My expert search")

    def test_name_optional_omitted(self):
        ser = ExpertSearchCreateSerializer(data={"query": "Q"})
        self.assertTrue(ser.is_valid())
        # When omitted, name may be absent (None) or "" depending on serializer
        self.assertFalse(ser.validated_data.get("name"))

    def test_additional_context_optional_with_query(self):
        ser = ExpertSearchCreateSerializer(
            data={"query": "Q", "additional_context": "Extra hints for the model."}
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(
            ser.validated_data["additional_context"], "Extra hints for the model."
        )

    def test_additional_context_optional_with_document(self):
        ser = ExpertSearchCreateSerializer(
            data={
                "unified_document_id": 42,
                "input_type": "abstract",
                "additional_context": "RFP nuance here.",
            }
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["additional_context"], "RFP nuance here.")

    def test_additional_context_max_length(self):
        ser = ExpertSearchCreateSerializer(
            data={
                "query": "q",
                "additional_context": "x" * (ADDITIONAL_CONTEXT_MAX_LENGTH + 1),
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("additional_context", ser.errors)


class ExpertSearchSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("ser")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Test",
            name="Test search",
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[],
            report_pdf_url="https://example.com/a.pdf",
            report_csv_url="https://example.com/a.csv",
        )
        e1 = Expert.objects.create(email="a@x.com", first_name="A")
        e2 = Expert.objects.create(email="b@x.com", first_name="B")
        SearchExpert.objects.create(expert_search=self.search, expert=e1, position=0)
        SearchExpert.objects.create(expert_search=self.search, expert=e2, position=1)

    def test_serializer_includes_name(self):
        ser = ExpertSearchSerializer(self.search)
        self.assertEqual(ser.data["name"], "Test search")

    def test_serializer_includes_additional_context(self):
        self.search.additional_context = "User notes"
        self.search.save(update_fields=["additional_context"])
        ser = ExpertSearchSerializer(self.search)
        self.assertEqual(ser.data["additional_context"], "User notes")

    def test_get_expert_names(self):
        ser = ExpertSearchSerializer(self.search)
        self.assertEqual(ser.data["expert_names"], ["A", "B"])

    def test_expert_results_include_last_email_sent_at(self):
        from django.utils import timezone

        ser = ExpertSearchSerializer(self.search)
        rows = ser.data["expert_results"]
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["last_email_sent_at"])
        e1 = Expert.objects.get(email="a@x.com")
        ts = timezone.now()
        Expert.objects.filter(pk=e1.pk).update(last_email_sent_at=ts)
        ser2 = ExpertSearchSerializer(self.search)
        rows2 = ser2.data["expert_results"]
        self.assertIsNotNone(rows2[0]["last_email_sent_at"])
        self.assertIsNone(rows2[1]["last_email_sent_at"])

    def test_get_report_urls(self):
        ser = ExpertSearchSerializer(self.search)
        self.assertEqual(
            ser.data["report_urls"],
            {"pdf": "https://example.com/a.pdf", "csv": "https://example.com/a.csv"},
        )

    def test_get_expert_names_empty(self):
        SearchExpert.objects.filter(expert_search=self.search).delete()
        ser = ExpertSearchSerializer(self.search)
        self.assertEqual(ser.data["expert_names"], [])

    def test_get_report_urls_none_when_empty(self):
        self.search.report_pdf_url = ""
        self.search.report_csv_url = ""
        self.search.save()
        ser = ExpertSearchSerializer(self.search)
        self.assertIsNone(ser.data["report_urls"])

    def test_created_by_payload_has_user_id_and_author_key(self):
        ser = ExpertSearchSerializer(self.search)
        created_by = ser.data["created_by"]
        self.assertEqual(created_by["user_id"], self.user.id)
        self.assertIn("author", created_by)
        if created_by["author"] is not None:
            self.assertIn("id", created_by["author"])

    def test_work_is_none_when_no_unified_document(self):
        """ExpertSearch without unified_document has work=None."""
        ser = ExpertSearchSerializer(self.search)
        self.assertIsNone(self.search.unified_document_id)
        self.assertIsNone(ser.data["work"])

    def test_work_resolves_paper_when_unified_document_is_paper(self):
        """Unified doc pointing to paper yields work with type paper."""
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
        ser = ExpertSearchSerializer(search_with_paper)
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
            expert_results=[],
        )
        self.expert = Expert.objects.create(email="x@y.com", first_name="X")
        SearchExpert.objects.create(
            expert_search=self.search, expert=self.expert, position=0
        )

    def test_list_item_fields(self):
        ser = ExpertSearchListItemSerializer(self.search)
        self.assertEqual(ser.data["search_id"], self.search.id)
        self.assertEqual(ser.data["query"], "List test")
        self.assertEqual(ser.data["expert_names"], ["X"])
        self.assertEqual(ser.data["expert_ids"], [self.expert.id])

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
