from unittest import TestCase
from unittest.mock import Mock, patch

from researchhub_document.models import ResearchhubUnifiedDocument


class TestCensorUnifiedDocument(TestCase):

    @patch("discussion.views.remove_from_search_index")
    def test_resolves_unified_document_to_inner_doc(self, mock_remove):
        from discussion.views import censor

        inner_doc = Mock()
        item = Mock(spec=ResearchhubUnifiedDocument)
        item.get_document.return_value = inner_doc

        censor(item)

        item.get_document.assert_called_once()
        mock_remove.assert_called_once_with(inner_doc)
