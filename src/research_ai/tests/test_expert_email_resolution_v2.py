from django.test import TestCase

from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.expert_email_resolution_v2 import (
    resolve_expert_from_search_v2,
)
from user.tests.helpers import create_random_authenticated_user


class ResolveExpertFromSearchV2Tests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("res_v2_user")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Q",
            status=ExpertSearch.Status.COMPLETED,
            expert_count=1,
        )

    def test_returns_none_without_search(self):
        self.assertIsNone(resolve_expert_from_search_v2(None, "a@b.edu"))

    def test_returns_none_for_blank_email(self):
        self.assertIsNone(resolve_expert_from_search_v2(self.search, ""))
        self.assertIsNone(resolve_expert_from_search_v2(self.search, "   "))

    def test_returns_none_when_not_linked_to_search(self):
        Expert.objects.create(
            email="orphan@edu",
            first_name="O",
            last_name="R",
        )
        self.assertIsNone(
            resolve_expert_from_search_v2(self.search, "orphan@edu"),
        )

    def test_returns_dict_matching_generate_expert_email_shape(self):
        ex = Expert.objects.create(
            email="Ada@Uni.EDU",
            honorific="Dr",
            first_name="Ada",
            middle_name="M",
            last_name="Lovelace",
            academic_title="Professor",
            affiliation="Uni",
            expertise="Computing",
            notes="Note text",
        )
        SearchExpert.objects.create(expert_search=self.search, expert=ex, position=0)
        out = resolve_expert_from_search_v2(self.search, " ada@uni.edu ")
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["email"], "ada@uni.edu")
        self.assertEqual(out["title"], "Professor")
        self.assertEqual(out["affiliation"], "Uni")
        self.assertEqual(out["expertise"], "Computing")
        self.assertEqual(out["notes"], "Note text")
        self.assertIn("Lovelace", out["name"])
