from contextlib import ExitStack
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

from opensearchpy.exceptions import ConnectionError as OpenSearchConnectionError

from hub.models import Hub
from paper.models import Paper
from paper.tests.helpers import create_paper
from researchhub_document.related_models.constants.document_type import DISCUSSION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user

COMMAND = "remove_deleted_docs_from_index"
PATCH_PREFIX = f"search.management.commands.{COMMAND}"
DOC_CLASSES = ("PaperDocument", "PostDocument", "HubDocument", "JournalDocument")


def _mock_mget_all_found(index, body):
    return {"docs": [{"_id": doc_id, "found": True} for doc_id in body["ids"]]}


def _mock_mget_none_found(index, body):
    return {"docs": [{"_id": doc_id, "found": False} for doc_id in body["ids"]]}


def _mock_client(mget_func=_mock_mget_all_found):
    return Mock(mget=mget_func)


def _get_updated_ids(mock_update):
    return [obj.id for obj in mock_update.call_args[0][0]]


def _patch_all_connections(mget_func=_mock_mget_all_found):
    """Context manager that patches _get_connection for all document classes."""
    client = _mock_client(mget_func)
    stack = ExitStack()
    for cls in DOC_CLASSES:
        stack.enter_context(
            patch(f"{PATCH_PREFIX}.{cls}._get_connection", return_value=client)
        )
    return stack


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

        self.user = create_random_authenticated_user("testuser")

        self.unified_doc_removed = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION, is_removed=True
        )
        self.post_removed = ResearchhubPost.objects.create(
            unified_document=self.unified_doc_removed,
            created_by=self.user,
            title="Removed Post",
        )

        self.unified_doc_active = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION, is_removed=False
        )
        self.post_active = ResearchhubPost.objects.create(
            unified_document=self.unified_doc_active,
            created_by=self.user,
            title="Active Post",
        )

    def _patch_connection(self, doc_class, mget_func=_mock_mget_all_found):
        return patch(
            f"{PATCH_PREFIX}.{doc_class}._get_connection",
            return_value=_mock_client(mget_func),
        )

    # --- Dry run ---

    def test_dry_run_reports_counts_but_does_not_modify(self):
        # Arrange
        out = StringIO()

        # Act
        with _patch_all_connections(), patch(
            f"{PATCH_PREFIX}.PaperDocument.update"
        ) as mock_update:
            call_command(COMMAND, "--dry-run", stdout=out)

        # Assert
        mock_update.assert_not_called()
        output = out.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("1 still in index", output)

    # --- Index filtering ---

    def test_index_flag_restricts_to_single_index(self):
        # Arrange / Act
        with self._patch_connection("PaperDocument"), patch(
            f"{PATCH_PREFIX}.PaperDocument.update"
        ) as mock_paper, patch(
            f"{PATCH_PREFIX}.PostDocument.update"
        ) as mock_post:
            call_command(COMMAND, "--index=paper", stdout=StringIO())

        # Assert
        mock_paper.assert_called_once()
        mock_post.assert_not_called()

    def test_processes_all_indices_when_no_flag_provided(self):
        # Arrange
        mocks = {}

        # Act
        with _patch_all_connections(), ExitStack() as stack:
            for cls in DOC_CLASSES:
                mocks[cls] = stack.enter_context(
                    patch(f"{PATCH_PREFIX}.{cls}.update")
                )
            call_command(COMMAND, stdout=StringIO())

        # Assert
        for cls, mock_update in mocks.items():
            mock_update.assert_called_once()

    # --- Paper index ---

    def test_paper_index_only_includes_removed_papers(self):
        # Arrange / Act
        with self._patch_connection("PaperDocument"), patch(
            f"{PATCH_PREFIX}.PaperDocument.update"
        ) as mock_update:
            call_command(COMMAND, "--index=paper", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.paper_removed.id, ids)
        self.assertNotIn(self.paper_active.id, ids)

    # --- Post index ---

    def test_post_index_uses_unified_document_removal_status(self):
        # Arrange / Act
        with self._patch_connection("PostDocument"), patch(
            f"{PATCH_PREFIX}.PostDocument.update"
        ) as mock_update:
            call_command(COMMAND, "--index=post", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.post_removed.id, ids)
        self.assertNotIn(self.post_active.id, ids)

    # --- Hub index ---

    def test_hub_index_excludes_journals(self):
        # Arrange / Act
        with self._patch_connection("HubDocument"), patch(
            f"{PATCH_PREFIX}.HubDocument.update"
        ) as mock_update:
            call_command(COMMAND, "--index=hub", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.hub_removed.id, ids)
        self.assertNotIn(self.journal_removed.id, ids)
        self.assertNotIn(self.hub_active.id, ids)

    # --- Journal index ---

    def test_journal_index_only_includes_removed_journals(self):
        # Arrange / Act
        with self._patch_connection("JournalDocument"), patch(
            f"{PATCH_PREFIX}.JournalDocument.update"
        ) as mock_update:
            call_command(COMMAND, "--index=journal", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.journal_removed.id, ids)
        self.assertNotIn(self.hub_removed.id, ids)

    # --- OpenSearch awareness ---

    def test_skips_removal_when_docs_not_in_index(self):
        # Arrange / Act
        with self._patch_connection("PaperDocument", _mock_mget_none_found), patch(
            f"{PATCH_PREFIX}.PaperDocument.update"
        ) as mock_update:
            out = StringIO()
            call_command(COMMAND, "--index=paper", stdout=out)

        # Assert
        mock_update.assert_not_called()
        self.assertIn("0 still in index", out.getvalue())

    def test_skips_opensearch_check_when_no_removed_docs_in_database(self):
        # Arrange
        Paper.objects.filter(is_removed=True).update(is_removed=False)

        # Act
        with patch(
            f"{PATCH_PREFIX}.PaperDocument._get_connection"
        ) as mock_conn, patch(
            f"{PATCH_PREFIX}.PaperDocument.update"
        ) as mock_update:
            call_command(COMMAND, "--index=paper", stdout=StringIO())

        # Assert
        mock_conn.assert_not_called()
        mock_update.assert_not_called()

    # --- Error handling ---

    def test_update_exception_is_logged_without_aborting(self):
        # Arrange
        out = StringIO()
        err = StringIO()

        # Act
        with self._patch_connection("PaperDocument"), patch(
            f"{PATCH_PREFIX}.PaperDocument.update",
            side_effect=Exception("Connection error"),
        ):
            call_command(COMMAND, "--index=paper", stdout=out, stderr=err)

        # Assert
        self.assertIn("Error in Papers", err.getvalue())
        self.assertIn("Done", out.getvalue())

    def test_mget_exception_is_handled_gracefully(self):
        # Arrange
        def mget_raises(index, body):
            raise OpenSearchConnectionError("OpenSearch unavailable")

        out = StringIO()
        err = StringIO()

        # Act
        with self._patch_connection("PaperDocument", mget_raises), patch(
            f"{PATCH_PREFIX}.PaperDocument.update"
        ) as mock_update:
            call_command(COMMAND, "--index=paper", stdout=out, stderr=err)

        # Assert
        mock_update.assert_not_called()
        self.assertIn("Error checking index", err.getvalue())


