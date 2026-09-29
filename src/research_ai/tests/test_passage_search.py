from unittest import TestCase

from research_ai.services.passage_search import relevant_passages


class RelevantPassagesTests(TestCase):
    def test_documents_share_one_index_so_scores_compare(self):
        # Arrange
        documents = [
            "Budget justification for sequencing costs.",
            "Aims: map enhancer activity in cortical organoids.",
        ]

        # Act
        passages = relevant_passages(documents, "enhancer organoids", limit=2)

        # Assert
        self.assertEqual(passages[0].document, 1)
        self.assertIn("enhancer", passages[0].text)
        self.assertEqual(len(passages), 1)

    def test_overlapping_windows_are_suppressed_within_a_document_only(self):
        # Arrange: long enough for overlapping windows around the phrase.
        filler = " ".join(["background"] * 300)
        text = f"{filler} pooled crispr screen {filler}"

        # Act
        passages = relevant_passages([text, text], "pooled crispr screen", limit=5)

        # Assert: one passage per document, never two overlapping ones.
        self.assertEqual(sorted(passage.document for passage in passages), [0, 1])
        self.assertTrue(all("crispr" in passage.text for passage in passages))

    def test_nothing_to_rank_returns_no_passages(self):
        # Act / Assert
        self.assertEqual(relevant_passages([], "crispr", limit=3), [])
        self.assertEqual(relevant_passages([""], "crispr", limit=3), [])
        self.assertEqual(relevant_passages(["!!! ---", "   "], "crispr", limit=3), [])
        self.assertEqual(relevant_passages(["crispr screen"], "  ", limit=3), [])
