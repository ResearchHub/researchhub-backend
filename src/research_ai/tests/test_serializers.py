from django.test import TestCase

from research_ai.constants import ExpertiseLevel, Gender, Region
from research_ai.models import ExpertSearch
from research_ai.serializers import (
    ExpertSearchConfigSerializer,
    ExpertSearchCreateSerializer,
    ExpertSearchListItemSerializer,
    ExpertSearchSerializer,
    GeneratedEmailSerializer,
)
from user.tests.helpers import create_random_authenticated_user


class ExpertSearchConfigSerializerTests(TestCase):
    def test_default_values(self):
        ser = ExpertSearchConfigSerializer(data={})
        self.assertTrue(ser.is_valid())
        data = ser.validated_data
        self.assertEqual(data["expert_count"], 10)
        self.assertEqual(data["expertise_level"], ExpertiseLevel.ALL_LEVELS)
        self.assertEqual(data["region"], Region.ALL_REGIONS)
        self.assertEqual(data["gender"], Gender.ALL_GENDERS)

    def test_camelCase_fallback(self):
        ser = ExpertSearchConfigSerializer(
            data={
                "expertCount": 15,
                "expertiseLevel": ExpertiseLevel.EARLY_CAREER,
                "genderPreference": Gender.FEMALE,
            }
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["expert_count"], 15)
        self.assertEqual(ser.validated_data["expertise_level"], ExpertiseLevel.EARLY_CAREER)
        self.assertEqual(ser.validated_data["gender"], Gender.FEMALE)

    def test_expert_count_bounds(self):
        ser = ExpertSearchConfigSerializer(data={"expert_count": 5})
        self.assertTrue(ser.is_valid())
        ser = ExpertSearchConfigSerializer(data={"expert_count": 20})
        self.assertTrue(ser.is_valid())
        ser = ExpertSearchConfigSerializer(data={"expert_count": 4})
        self.assertFalse(ser.is_valid())
        ser = ExpertSearchConfigSerializer(data={"expert_count": 21})
        self.assertFalse(ser.is_valid())


class ExpertSearchCreateSerializerTests(TestCase):
    def test_query_only_valid(self):
        ser = ExpertSearchCreateSerializer(data={"query": "Machine learning"})
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["query"], "Machine learning")
        self.assertEqual(ser.validated_data["input_type"], ExpertSearch.InputType.ABSTRACT)

    def test_unified_document_id_only_valid(self):
        ser = ExpertSearchCreateSerializer(data={"unified_document_id": 123})
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["unified_document_id"], 123)

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

    def test_excluded_expert_names_camelCase(self):
        ser = ExpertSearchCreateSerializer(
            data={"query": "Bar", "excludedExpertNames": ["Alice", "Bob"]}
        )
        self.assertTrue(ser.is_valid())
        self.assertEqual(ser.validated_data["excluded_expert_names"], ["Alice", "Bob"])


class ExpertSearchSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("ser")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Test",
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[
                {"name": "A", "email": "a@x.com"},
                {"name": "B", "email": "b@x.com"},
            ],
            report_pdf_url="https://example.com/a.pdf",
            report_csv_url="https://example.com/a.csv",
        )

    def test_get_expert_names(self):
        ser = ExpertSearchSerializer(self.search)
        self.assertEqual(ser.data["expert_names"], ["A", "B"])

    def test_get_report_urls(self):
        ser = ExpertSearchSerializer(self.search)
        self.assertEqual(ser.data["report_urls"], {"pdf": "https://example.com/a.pdf", "csv": "https://example.com/a.csv"})

    def test_get_expert_names_empty(self):
        self.search.expert_results = []
        self.search.save()
        ser = ExpertSearchSerializer(self.search)
        self.assertEqual(ser.data["expert_names"], [])

    def test_get_report_urls_none_when_empty(self):
        self.search.report_pdf_url = ""
        self.search.report_csv_url = ""
        self.search.save()
        ser = ExpertSearchSerializer(self.search)
        self.assertIsNone(ser.data["report_urls"])


class ExpertSearchListItemSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("list")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="List test",
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[{"name": "X", "email": "x@y.com"}],
        )

    def test_list_item_fields(self):
        ser = ExpertSearchListItemSerializer(self.search)
        self.assertEqual(ser.data["search_id"], self.search.id)
        self.assertEqual(ser.data["query"], "List test")
        self.assertEqual(ser.data["expert_names"], ["X"])


class GeneratedEmailSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("email_ser")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
        )

    def test_serialize_generated_email(self):
        from research_ai.models import GeneratedEmail

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
