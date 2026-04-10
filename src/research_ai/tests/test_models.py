from django.db import IntegrityError
from django.test import TestCase

from research_ai.constants import EmailTemplateType
from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from user.tests.helpers import create_random_authenticated_user


class ExpertSearchModelTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("expert_search")

    def test_create_expert_search_with_query(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Machine learning in healthcare",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
            status=ExpertSearch.Status.PENDING,
        )
        self.assertEqual(search.query, "Machine learning in healthcare")
        self.assertEqual(search.input_type, ExpertSearch.InputType.CUSTOM_QUERY)
        self.assertEqual(search.status, ExpertSearch.Status.PENDING)
        self.assertEqual(search.progress, 0)

    def test_create_expert_search_with_config(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Climate change",
            config={"expert_count": 15},
            status=ExpertSearch.Status.COMPLETED,
            expert_results=[{"name": "Jane Doe", "email": "jane@example.com"}],
            expert_count=1,
        )
        self.assertEqual(search.config["expert_count"], 15)
        self.assertEqual(len(search.expert_results), 1)

    def test_additional_context_optional_defaults_empty(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
        )
        self.assertEqual(search.additional_context, "")

    def test_additional_context_persisted(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="RFP text",
            additional_context="Steer toward EU labs.",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
        )
        self.assertEqual(search.additional_context, "Steer toward EU labs.")

    def test_expert_search_str(self):
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Test",
            status=ExpertSearch.Status.PROCESSING,
        )
        self.assertIn(str(search.id), str(search))
        self.assertIn(ExpertSearch.Status.PROCESSING, str(search))

    def test_input_type_and_status_choices(self):
        self.assertEqual(ExpertSearch.InputType.CUSTOM_QUERY, "custom_query")
        self.assertEqual(ExpertSearch.Status.COMPLETED, "completed")


class GeneratedEmailModelTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("gen_email")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Test query",
            status=ExpertSearch.Status.COMPLETED,
        )

    def test_create_generated_email(self):
        email = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.expert_search,
            expert_name="Dr. Jane Doe",
            expert_email="jane@university.edu",
            template=EmailTemplateType.COLLABORATION,
        )
        self.assertEqual(email.expert_name, "Dr. Jane Doe")
        self.assertEqual(email.template, EmailTemplateType.COLLABORATION.value)
        self.assertEqual(email.status, GeneratedEmail.Status.DRAFT)

    def test_generated_email_str(self):
        email = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_name="John Smith",
            expert_email="john@example.com",
        )
        self.assertIn("John Smith", str(email))


class ExpertAndSearchExpertModelTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("expert_row")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
        )

    def test_expert_email_unique_case_insensitive(self):
        Expert.objects.create(email="a@b.com", first_name="A")
        with self.assertRaises(IntegrityError):
            Expert.objects.create(email="A@B.COM", first_name="B")

    def test_search_expert_unique_per_search(self):
        e = Expert.objects.create(email="x@y.org")
        SearchExpert.objects.create(expert_search=self.search, expert=e, position=0)
        with self.assertRaises(Exception):
            SearchExpert.objects.create(expert_search=self.search, expert=e, position=1)
