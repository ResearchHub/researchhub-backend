from django.core.management import call_command
from django.test import TestCase

from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.expert_results_legacy_migration import (
    legacy_expert_result_row_to_parsed_dict,
    legacy_expert_results_to_persist_rows,
    split_legacy_display_name_for_migration,
)
from user.tests.helpers import create_random_authenticated_user


class SplitLegacyDisplayNameTests(TestCase):
    def test_last_first_comma_form(self):
        p = split_legacy_display_name_for_migration("Smith, John")
        self.assertEqual(p["last_name"], "Smith")
        self.assertEqual(p["first_name"], "John")
        self.assertEqual(p["middle_name"], "")

    def test_last_first_middle_comma_form(self):
        p = split_legacy_display_name_for_migration("Smith, John Q.")
        self.assertEqual(p["last_name"], "Smith")
        self.assertEqual(p["first_name"], "John")
        self.assertEqual(p["middle_name"], "Q.")

    def test_honorific_and_trailing_suffix(self):
        p = split_legacy_display_name_for_migration("Dr. Jane Q. Public, PhD")
        self.assertEqual(p["honorific"], "Dr.")
        self.assertEqual(p["first_name"], "Jane")
        self.assertEqual(p["middle_name"], "Q.")
        self.assertEqual(p["last_name"], "Public")
        self.assertEqual(p["name_suffix"], "PhD")

    def test_two_tokens(self):
        p = split_legacy_display_name_for_migration("Jane Public")
        self.assertEqual(p["first_name"], "Jane")
        self.assertEqual(p["last_name"], "Public")

    def test_single_token_goes_to_last_name(self):
        p = split_legacy_display_name_for_migration("Cher")
        self.assertEqual(p["first_name"], "")
        self.assertEqual(p["last_name"], "Cher")


class LegacyExpertResultRowTests(TestCase):
    def test_maps_title_to_academic_title(self):
        d = legacy_expert_result_row_to_parsed_dict(
            {
                "name": "Dr. A",
                "title": "Professor",
                "affiliation": "MIT",
                "expertise": "ML",
                "email": "A@MIT.EDU",
                "notes": "n",
                "sources": [{"text": "t", "url": "https://x"}],
            }
        )
        assert d is not None
        self.assertEqual(d["email"], "a@mit.edu")
        self.assertEqual(d["academic_title"], "Professor")
        self.assertEqual(d["affiliation"], "MIT")
        self.assertEqual(d["sources"], [{"text": "t", "url": "https://x"}])

    def test_invalid_email_returns_none(self):
        self.assertIsNone(
            legacy_expert_result_row_to_parsed_dict(
                {"name": "X", "email": "not-an-email"}
            )
        )

    def test_prefers_structured_name_fields(self):
        d = legacy_expert_result_row_to_parsed_dict(
            {
                "first_name": "Pat",
                "last_name": "Lee",
                "honorific": "Dr.",
                "email": "pat@x.org",
                "name": "Ignored Name",
            }
        )
        assert d is not None
        self.assertEqual(d["first_name"], "Pat")
        self.assertEqual(d["last_name"], "Lee")
        self.assertEqual(d["honorific"], "Dr.")


class LegacyExpertResultsDedupeTests(TestCase):
    def test_dedupes_by_email_preserving_order(self):
        rows = legacy_expert_results_to_persist_rows(
            [
                {"name": "A", "email": "dup@x.com"},
                {"name": "B", "email": "dup@x.com"},
                {"name": "C", "email": "other@x.com"},
            ]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["email"], "dup@x.com")
        self.assertEqual(rows[1]["email"], "other@x.com")


class MigrateExpertResultsCommandTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("migrate_cmd_user")

    def test_dry_run_does_not_create_search_expert(self):
        from io import StringIO

        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="q",
            expert_results=[
                {
                    "name": "Dr. Test",
                    "title": "Prof",
                    "affiliation": "U",
                    "expertise": "x",
                    "email": "tester@university.edu",
                    "notes": "",
                    "sources": [],
                }
            ],
        )
        call_command(
            "migrate_expert_results_to_models",
            dry_run=True,
            stdout=StringIO(),
        )
        self.assertEqual(SearchExpert.objects.filter(expert_search=search).count(), 0)

    def test_migrate_creates_expert_and_search_expert(self):
        from io import StringIO

        buf = StringIO()
        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="q",
            expert_results=[
                {
                    "name": "Dr. Test",
                    "title": "Prof",
                    "affiliation": "U",
                    "expertise": "x",
                    "email": "migrate_one@university.edu",
                    "notes": "",
                    "sources": [],
                }
            ],
        )
        call_command("migrate_expert_results_to_models", stdout=buf)
        self.assertEqual(SearchExpert.objects.filter(expert_search=search).count(), 1)
        ex = Expert.objects.get(email="migrate_one@university.edu")
        self.assertEqual(ex.academic_title, "Prof")
        self.assertIn("migrated", buf.getvalue().lower())

    def test_skips_when_search_expert_exists_unless_force(self):
        from io import StringIO

        search = ExpertSearch.objects.create(
            created_by=self.user,
            query="q",
            expert_results=[
                {
                    "name": "X",
                    "title": "",
                    "affiliation": "",
                    "expertise": "",
                    "email": "exists@university.edu",
                    "notes": "",
                    "sources": [],
                }
            ],
        )
        expert = Expert.objects.create(email="exists@university.edu")
        SearchExpert.objects.create(
            expert_search=search, expert=expert, position=0
        )
        buf = StringIO()
        call_command("migrate_expert_results_to_models", stdout=buf)
        self.assertEqual(SearchExpert.objects.filter(expert_search=search).count(), 1)

        buf2 = StringIO()
        call_command(
            "migrate_expert_results_to_models",
            force_replace=True,
            stdout=buf2,
        )
        self.assertEqual(SearchExpert.objects.filter(expert_search=search).count(), 1)
        se = SearchExpert.objects.get(expert_search=search)
        self.assertEqual(se.expert.email, "exists@university.edu")
