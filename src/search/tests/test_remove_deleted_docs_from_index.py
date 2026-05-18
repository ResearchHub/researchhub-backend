from contextlib import ExitStack
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

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
    return Mock(mget=Mock(side_effect=mget_func))


def _get_updated_ids(mock_update):
    return [obj.id for obj in mock_update.call_args[0][0]]


def _patch_all_connections(mget_func=_mock_mget_all_found):
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

        self.hub_removed = Hub.objects.create(name="Removed Hub", is_removed=True)
        self.journal_removed = Hub.objects.create(
            name="Removed Journal", is_removed=True, namespace="journal"
        )

        self.user = create_random_authenticated_user("testuser")

        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION, is_removed=True
        )
        self.post_removed = ResearchhubPost.objects.create(
            unified_document=unified_doc,
            created_by=self.user,
            title="Removed Post",
        )

    def _patch_connection(self, doc_class, mget_func=_mock_mget_all_found):
        return patch(
            f"{PATCH_PREFIX}.{doc_class}._get_connection",
            return_value=_mock_client(mget_func),
        )

    # --- Core behavior ---

    def test_only_removed_objects_are_sent_to_update(self):
        # Arrange / Act
        with (
            self._patch_connection("PaperDocument"),
            patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_update,
        ):
            call_command(COMMAND, "--index=paper", stdout=StringIO())

        # Assert
        ids = _get_updated_ids(mock_update)
        self.assertIn(self.paper_removed.id, ids)
        self.assertNotIn(self.paper_active.id, ids)

    def test_processes_all_indices_when_no_flag_provided(self):
        # Arrange
        mocks = {}

        # Act
        with _patch_all_connections(), ExitStack() as stack:
            for cls in DOC_CLASSES:
                mocks[cls] = stack.enter_context(patch(f"{PATCH_PREFIX}.{cls}.update"))
            call_command(COMMAND, stdout=StringIO())

        # Assert
        for cls, mock_update in mocks.items():
            mock_update.assert_called_once()

    def test_index_flag_restricts_to_single_index(self):
        # Arrange / Act
        with (
            self._patch_connection("PaperDocument"),
            patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_paper,
            patch(f"{PATCH_PREFIX}.PostDocument.update") as mock_post,
        ):
            call_command(COMMAND, "--index=paper", stdout=StringIO())

        # Assert
        mock_paper.assert_called_once()
        mock_post.assert_not_called()

    # --- Dry run ---

    def test_dry_run_reports_counts_but_does_not_modify(self):
        # Arrange
        out = StringIO()

        # Act
        with (
            _patch_all_connections(),
            patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_update,
        ):
            call_command(COMMAND, "--dry-run", stdout=out)

        # Assert
        mock_update.assert_not_called()
        output = out.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("1 still in index", output)

    # --- OpenSearch awareness ---

    def test_skips_removal_when_docs_not_in_index(self):
        # Arrange / Act
        with (
            self._patch_connection("PaperDocument", _mock_mget_none_found),
            patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_update,
        ):
            out = StringIO()
            call_command(COMMAND, "--index=paper", stdout=out)

        # Assert
        mock_update.assert_not_called()
        self.assertIn("0 still in index", out.getvalue())

    def test_skips_removal_when_no_removed_docs_in_database(self):
        # Arrange
        Paper.objects.filter(is_removed=True).update(is_removed=False)
        client = _mock_client()
        out = StringIO()

        # Act
        with (
            patch(
                f"{PATCH_PREFIX}.PaperDocument._get_connection",
                return_value=client,
            ),
            patch(f"{PATCH_PREFIX}.PaperDocument.update") as mock_update,
        ):
            call_command(COMMAND, "--index=paper", stdout=out)

        # Assert
        client.mget.assert_not_called()
        mock_update.assert_not_called()
        self.assertIn("0 removed in database", out.getvalue())
