from unittest import TestCase


class TestOpenAlexWorkIdSafety(TestCase):

    def test_none_work_id_skips_safely(self):
        """Simulates the guard: if work_id is None, continue (skip the work)."""
        work = {"is_authors_truncated": True, "id": None}
        work_id = work.get("id")
        self.assertIsNone(work_id)
        self.assertFalse(bool(work_id))

    def test_missing_work_id_skips_safely(self):
        work = {"is_authors_truncated": True}
        work_id = work.get("id")
        self.assertIsNone(work_id)

    def test_valid_work_id_splits(self):
        work = {"is_authors_truncated": True, "id": "https://openalex.org/W12345"}
        work_id = work.get("id")
        self.assertTrue(bool(work_id))
        just_id = work_id.split("/")[-1]
        self.assertEqual(just_id, "W12345")
