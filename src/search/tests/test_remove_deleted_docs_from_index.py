from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from hub.models import Hub
from paper.models import Paper
from paper.tests.helpers import create_paper
from researchhub_document.related_models.constants.document_type import (
    POST as POST_DOC_TYPE,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

COMMAND = "remove_deleted_docs_from_index"
PATCH_PREFIX = f"search.management.commands.{COMMAND}"


def _get_updated_ids(mock_update):
    """Extract object IDs from the first positional arg passed to Document.update."""
    return [obj.id for obj in mock_update.call_args[0][0]]


class RemoveDeletedDocsFromIndexTests(TestCase):
    def setUp(self):
        self.paper_active = create_paper(title="Active Paper")
        self.paper_removed = create_paper(title="Removed Paper")
        self.paper_removed.is_removed = True
        self.paper_removed.save()

        self.hub_active = Hub.objects.create(name="Active Hub", is_removed=False)
        self.hub_removed = Hub.objects.create(name="Removed Hub", is_removed=True)
        self.journal_removed = Hub.objects.create(
            name="Removed Journal", is_removed=True, namespace="journal"
        )

        self.unified_doc_removed = ResearchhubUnifiedDocument.objects.create(
            document_type=POST_DOC_TYPE, is_removed=True
        )
        self.post_removed = ResearchhubPost.objects.create(
            unified_document=self.unified_doc_removed,
            created_by=None,
            title="Removed Post",
        )

        self.unified_doc_active = ResearchhubUnifiedDocument.objects.create(
            document_type=POST_DOC_TYPE, is_removed=False
        )
        self.post_active = ResearchhubPost.objects.create(
            unified_document=self.unified_doc_active,
            created_by=None,
            title="Active Post",
        )

    def test_dry_run_does_not_modify_index(self):
        # Arrange
        out = StringIO()

        # Act
        with patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_update:
            call_command(COMMAND, "--dry-run", stdout=out)

        # Assert
        mock_update.assert_not_called()
        output = out.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("Papers marked as removed: 1", output)

    def test_index_flag_restricts_to_single_index(self):
        # Arrange / Act
        with patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_paper, patch(
            f"{PATCH_PREFIX}.PostDocument.update"
        ) as mock_post:
            call_command(COMMAND, "--index=paper", stdout=StringIO())

        # Assert
        mock_paper.assert_called_once()
        mock_post.assert_not_called()

    def test_paper_index_only_includes_removed_papers(self):
        # Arrange / Act
        with patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_update:
            call_command(COMMAND, "--index=paper", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.paper_removed.id, ids)
        self.assertNotIn(self.paper_active.id, ids)

    def test_post_index_uses_unified_document_removal_status(self):
        # Arrange / Act
        with patch(f"{PATCH_PREFIX}.PostDocument.update") as mock_update:
            call_command(COMMAND, "--index=post", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.post_removed.id, ids)
        self.assertNotIn(self.post_active.id, ids)

    def test_hub_index_excludes_journals(self):
        # Arrange / Act
        with patch(f"{PATCH_PREFIX}.HubDocument.update") as mock_update:
            call_command(COMMAND, "--index=hub", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.hub_removed.id, ids)
        self.assertNotIn(self.journal_removed.id, ids)
        self.assertNotIn(self.hub_active.id, ids)

    def test_journal_index_only_includes_removed_journals(self):
        # Arrange / Act
        with patch(f"{PATCH_PREFIX}.JournalDocument.update") as mock_update:
            call_command(COMMAND, "--index=journal", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.journal_removed.id, ids)
        self.assertNotIn(self.hub_removed.id, ids)

    def test_exception_is_logged_without_aborting(self):
        # Arrange
        out = StringIO()
        err = StringIO()

        # Act
        with patch(
            f"{PATCH_PREFIX}.PaperDocument.update",
            side_effect=Exception("Connection error"),
        ):
            call_command(COMMAND, "--index=paper", stdout=out, stderr=err)

        # Assert
        self.assertIn("Error in paper", err.getvalue())
        self.assertIn("Done", out.getvalue())

    def test_skips_index_when_no_removed_docs_exist(self):
        # Arrange
        Paper.objects.filter(is_removed=True).update(is_removed=False)

        # Act
        with patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_update:
            call_command(COMMAND, "--index=paper", stdout=StringIO())

        # Assert
        mock_update.assert_not_called()

    def test_processes_all_indices_when_no_flag_provided(self):
        # Arrange / Act
        with patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_paper, patch(
            f"{PATCH_PREFIX}.PostDocument.update"
        ) as mock_post, patch(
            f"{PATCH_PREFIX}.HubDocument.update"
        ) as mock_hub, patch(
            f"{PATCH_PREFIX}.JournalDocument.update"
        ) as mock_journal:
            call_command(COMMAND, stdout=StringIO())

        # Assert
        mock_paper.assert_called_once()
        mock_post.assert_called_once()
        mock_hub.assert_called_once()
        mock_journal.assert_called_once()
