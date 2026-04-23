"""Unit tests for expert_display, expert_llm_table, expert_persist, expert_results_payload."""

from django.test import TestCase
from django.utils import timezone

from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.expert_display import (
    build_expert_display_name,
    expert_dict_to_api_payload,
    expert_model_display_name,
    expert_name_for_generated_email_storage,
    expert_name_for_legacy_generated_email_storage,
    expert_title_for_generated_email_storage,
    expert_title_for_legacy_generated_email_storage,
    normalize_expert_email,
)
from research_ai.services.expert_llm_table import (
    EXPERT_LLM_TABLE_HEADERS,
    EXPERT_LLM_TABLE_HEADER_LINE,
    EXPERT_LLM_TABLE_SEPARATOR_LINE,
    ExpertTableSchemaError,
    clean_expert_table_url,
    extract_citations_from_notes,
    parse_expert_markdown_table_strict,
)
from research_ai.services.expert_persist import (
    mark_expert_last_email_sent_at,
    replace_search_experts_for_search,
    upsert_expert_from_parsed_dict,
)
from research_ai.services.expert_results_payload import (
    expert_model_to_flat_dict,
    get_expert_results_payload,
)
from user.tests.helpers import create_user


# --- expert_display ---


class ExpertDisplayTests(TestCase):
    def test_build_expert_display_name_joins_parts_and_suffix(self):
        self.assertEqual(
            build_expert_display_name(
                honorific="Dr",
                first_name="Jane",
                middle_name="Q",
                last_name="Smith",
                name_suffix="PhD",
            ),
            "Dr Jane Q Smith, PhD",
        )

    def test_normalize_expert_email(self):
        self.assertEqual(
            normalize_expert_email("  Test@EXAMPLE.com "),
            "test@example.com",
        )
        self.assertEqual(normalize_expert_email(None), "")

    def test_expert_model_display_name_uses_expert_instance(self):
        e = Expert(
            email="a@b.com",
            honorific="Prof",
            first_name="A",
            middle_name="",
            last_name="B",
            name_suffix="",
        )
        self.assertEqual(expert_model_display_name(e), "Prof A B")

    def test_expert_dict_to_api_payload_structured_and_legacy(self):
        structured = expert_dict_to_api_payload(
            {
                "honorific": "Dr",
                "first_name": "X",
                "last_name": "Y",
                "academic_title": "Professor",
            }
        )
        self.assertEqual(structured["name"], "Dr X Y")
        self.assertEqual(structured["title"], "Professor")
        self.assertEqual(structured["academic_title"], "Professor")

        legacy = expert_dict_to_api_payload(
            {"name": "Only Name", "title": "Title X", "email": "e@e.com"}
        )
        self.assertEqual(legacy["name"], "Only Name")
        self.assertEqual(legacy["title"], "Title X")
        self.assertEqual(legacy["academic_title"], "Title X")

    def test_expert_name_and_title_for_generated_email_storage(self):
        row = {
            "honorific": "Dr",
            "first_name": "J",
            "last_name": "Doe",
            "academic_title": "Prof",
        }
        self.assertEqual(
            expert_name_for_generated_email_storage(row),
            "Dr J Doe",
        )
        self.assertEqual(
            expert_title_for_generated_email_storage(row),
            "Prof",
        )

    def test_expert_name_and_title_legacy_only_rows(self):
        legacy = {"name": "Legacy Name", "title": "Title X", "email": "e@e.com"}
        self.assertEqual(expert_name_for_generated_email_storage(legacy), "")
        self.assertEqual(expert_title_for_generated_email_storage(legacy), "")
        self.assertEqual(
            expert_name_for_legacy_generated_email_storage(legacy),
            "Legacy Name",
        )
        self.assertEqual(
            expert_title_for_legacy_generated_email_storage(legacy),
            "Title X",
        )


# --- expert_llm_table ---


class ExpertLlmTableTests(TestCase):
    def test_header_and_separator_line_column_count(self):
        n = len(EXPERT_LLM_TABLE_HEADERS)
        self.assertEqual(n, 10)
        self.assertEqual(EXPERT_LLM_TABLE_HEADER_LINE.count("|"), n + 1)
        self.assertEqual(EXPERT_LLM_TABLE_SEPARATOR_LINE.count("---"), n)

    def test_parse_strict_two_rows(self):
        md = f"""
{EXPERT_LLM_TABLE_HEADER_LINE}
{EXPERT_LLM_TABLE_SEPARATOR_LINE}
| Dr | Jane |  | Smith | PhD | Professor | MIT | ML | jane@mit.edu | See [p](https://q.com) |
|  | John | M | Smith |  | Dr | Stanford | CS | john@stanford.edu | n |
"""
        out = parse_expert_markdown_table_strict(md)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["email"], "jane@mit.edu")
        self.assertEqual(out[0]["first_name"], "Jane")
        self.assertEqual(out[0]["last_name"], "Smith")
        self.assertEqual(out[0]["academic_title"], "Professor")
        self.assertEqual(out[0]["name_suffix"], "PhD")
        self.assertEqual(len(out[0]["sources"]), 1)
        self.assertEqual(out[1]["email"], "john@stanford.edu")
        self.assertEqual(out[1]["first_name"], "John")
        self.assertEqual(out[1]["last_name"], "Smith")

    def test_parse_preserves_empty_middle_column(self):
        h = EXPERT_LLM_TABLE_HEADER_LINE
        s = EXPERT_LLM_TABLE_SEPARATOR_LINE
        md = f"""{h}
{s}
| | A |  | B | | | U | E | a@a.com | n |
"""
        out = parse_expert_markdown_table_strict(md)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["honorific"], "")
        self.assertEqual(out[0]["first_name"], "A")
        self.assertEqual(out[0]["middle_name"], "")

    def test_parse_skips_invalid_email(self):
        h = EXPERT_LLM_TABLE_HEADER_LINE
        s = EXPERT_LLM_TABLE_SEPARATOR_LINE
        md = f"""{h}
{s}
| | | | | | | | | bad | n |
| | j | | | | | | | j@j.com | n |
"""
        out = parse_expert_markdown_table_strict(md)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["email"], "j@j.com")

    def test_parse_raises_on_bad_header(self):
        h = EXPERT_LLM_TABLE_HEADER_LINE.replace("Honorific", "Wrong")
        s = EXPERT_LLM_TABLE_SEPARATOR_LINE
        with self.assertRaises(ExpertTableSchemaError):
            parse_expert_markdown_table_strict(
                f"""{h}
{s}
| | | | | | | | | x@x.com | n |
"""
            )

    def test_parse_raises_on_row_wrong_length(self):
        h = EXPERT_LLM_TABLE_HEADER_LINE
        s = EXPERT_LLM_TABLE_SEPARATOR_LINE
        with self.assertRaises(ExpertTableSchemaError):
            parse_expert_markdown_table_strict(
                f"""{h}
{s}
| a | b | c |
"""
            )

    def test_parse_raises_on_no_table(self):
        with self.assertRaises(ExpertTableSchemaError):
            parse_expert_markdown_table_strict("no pipes here at all")

    def test_extract_citations_and_clean_url(self):
        text = "X [L](https://e.com/l?utm_abc=1&x=1) y"
        clean, cits = extract_citations_from_notes(text)
        self.assertEqual(len(cits), 1)
        self.assertIn("e.com", cits[0]["url"])
        self.assertNotIn("utm_", cits[0]["url"])
        self.assertNotIn("L", clean)
        self.assertEqual(
            clean_expert_table_url("https://x.com"), "https://x.com"
        )
        self.assertEqual(
            clean_expert_table_url("https://x.com?utm_x=1&a=1"),
            "https://x.com?a=1",
        )


# --- expert_persist + expert_results_payload ---


class ExpertPersistAndPayloadTests(TestCase):
    def setUp(self):
        self.user = create_user(email="owner@test.com")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="q",
            status=ExpertSearch.Status.PENDING,
        )

    def _row(self, email: str, first: str = "F") -> dict:
        return {
            "honorific": "Dr",
            "first_name": first,
            "middle_name": "",
            "last_name": "L",
            "name_suffix": "",
            "academic_title": "Prof",
            "affiliation": "U",
            "expertise": "E",
            "email": email,
            "notes": "n",
            "sources": [],
        }

    def test_upsert_expert_from_parsed_dict_creates_and_updates(self):
        r = self._row("drift@u.edu", first="One")
        e1 = upsert_expert_from_parsed_dict(r)
        self.assertIsNotNone(e1.id)
        e1.refresh_from_db()
        self.assertEqual(e1.first_name, "One")
        r2 = self._row("drift@u.edu", first="Two")
        e2 = upsert_expert_from_parsed_dict(r2)
        self.assertEqual(e1.id, e2.id)
        e2.refresh_from_db()
        self.assertEqual(e2.first_name, "Two")

    def test_replace_search_experts_for_search_atomic_order(self):
        rows = [self._row("a1@u.edu", "A"), self._row("a2@u.edu", "B")]
        n = replace_search_experts_for_search(self.search.id, rows)
        self.assertEqual(n, 2)
        ses = list(
            SearchExpert.objects.filter(expert_search=self.search)
            .select_related("expert")
            .order_by("position")
        )
        self.assertEqual(ses[0].position, 0)
        self.assertEqual(ses[0].expert.email, "a1@u.edu")
        self.assertEqual(ses[1].expert.first_name, "B")

    def test_replace_clears_previous_search_experts(self):
        replace_search_experts_for_search(
            self.search.id, [self._row("only@u.edu")]
        )
        replace_search_experts_for_search(
            self.search.id, [self._row("new@u.edu")]
        )
        self.assertEqual(
            SearchExpert.objects.filter(expert_search=self.search).count(), 1
        )

    def test_replace_raises_when_search_missing(self):
        with self.assertRaises(ExpertSearch.DoesNotExist):
            replace_search_experts_for_search(999_999, [self._row("x@u.edu")])

    def test_mark_expert_last_email_sent_at(self):
        em = "mark@u.edu"
        expert = upsert_expert_from_parsed_dict(
            {**self._row(em), "affiliation": "X"}
        )
        ts = timezone.now()
        c = mark_expert_last_email_sent_at(em, at=ts)
        self.assertEqual(c, 1)
        expert.refresh_from_db()
        self.assertIsNotNone(expert.last_email_sent_at)

    def test_expert_model_to_flat_dict(self):
        ex = upsert_expert_from_parsed_dict(
            {**self._row("flat@u.edu", first="Jane"), "academic_title": "Assoc Prof"}
        )
        d = expert_model_to_flat_dict(ex)
        self.assertEqual(d["id"], ex.id)
        self.assertIn("Jane", d["name"])
        self.assertEqual(d["academic_title"], "Assoc Prof")
        self.assertEqual(d["title"], "Assoc Prof")

    def test_get_expert_results_payload_from_search_experts(self):
        replace_search_experts_for_search(
            self.search.id,
            [self._row("g1@u.edu"), self._row("g2@u.edu")],
        )
        out = get_expert_results_payload(self.search)
        self.assertEqual(len(out), 2)
        self.assertEqual(
            {r["email"] for r in out},
            {"g1@u.edu", "g2@u.edu"},
        )

    def test_get_expert_results_payload_falls_back_to_expert_results_json(self):
        self.search.expert_results = [
            {"name": "Legacy L", "title": "T", "email": "l@e.com", "expertise": "x"},
        ]
        self.search.save(update_fields=["expert_results"])
        out = get_expert_results_payload(self.search)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "Legacy L")
        self.assertEqual(out[0]["title"], "T")
        self.assertEqual(out[0]["email"], "l@e.com")

    def test_get_expert_results_payload_prefers_relational_over_json(self):
        self.search.expert_results = [
            {"name": "Json Only", "email": "j@e.com", "expertise": "x", "title": "t"},
        ]
        self.search.save()
        replace_search_experts_for_search(
            self.search.id, [self._row("db@u.edu", first="Db")]
        )
        out = get_expert_results_payload(self.search)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["email"], "db@u.edu")
        self.assertIn("Db", out[0]["name"])

    def test_get_expert_results_payload_empty(self):
        self.assertEqual(get_expert_results_payload(self.search), [])
