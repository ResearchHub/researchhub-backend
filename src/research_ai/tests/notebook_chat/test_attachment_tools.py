import json
from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.db.models.functions import Length
from django.test import TestCase

from research_ai.models import AgentFile
from research_ai.services.agent.tools import MAX_TOOL_RESULT_BYTES
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.agent_persistence.activity import ToolCallEvent
from research_ai.services.notebook_chat.activity import public_activity
from research_ai.services.notebook_chat.attachment_tools import (
    READ_ATTACHMENT,
    SEARCH_ATTACHMENT,
    AttachmentToolset,
    attachment_manifest,
)
from research_ai.tests.agent_files.helpers import make_file

# Each page outgrows one search window, so passages start on different pages.
FILLER = " ".join(["organoid"] * 180)
PDF_TEXT = (
    f"[Page 1]\nSpecific aims: map enhancer activity. {FILLER}\n\n"
    f"[Page 2]\nApproach: single-cell CRISPR screens across 40 donors. {FILLER}\n\n"
    f"[Page 3]\n{FILLER} Budget justification for sequencing costs."
)
CV_TEXT = "Education: PhD in genomics.\nAwards: early career award for CRISPR work."


class AttachmentToolsetTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        conversations = AgentConversationService()
        self.conversation = conversations.create(
            user=self.user, workflow="assistant_chat"
        )
        message = conversations.add_human_message(self.conversation, "See attached")
        self.proposal = make_file(self.user, message=message, text=PDF_TEXT)
        self.cv = make_file(
            self.user,
            message=message,
            filename="cv.txt",
            content_type="text/plain",
            text=CV_TEXT,
        )
        self.toolset = AttachmentToolset(conversation=self.conversation)

    def _call(self, name, args):
        result, stop = self.toolset.as_toolset().dispatch(name, args)
        self.assertFalse(stop)
        return result

    # -- read_attachment --------------------------------------------------

    def test_read_returns_the_whole_short_file(self):
        # Act
        result = self._call(READ_ATTACHMENT, {"attachment_id": self.proposal.id})

        # Assert
        self.assertEqual(result["text"], PDF_TEXT)
        self.assertEqual(result["filename"], "grant.pdf")
        self.assertEqual(result["total_chars"], len(PDF_TEXT))
        self.assertIsNone(result["next_start_char"])
        self.assertFalse(result["text_truncated"])

    def test_read_pages_through_a_long_file_on_line_breaks(self):
        # Arrange
        text = "".join(
            f"line {index:04d} of the methods section\n" for index in range(200)
        )
        long_file = make_file(
            self.user, message=self.proposal.message, filename="m.txt", text=text
        )

        # Act
        chunks, start = [], 0
        while start is not None:
            result = self._call(
                READ_ATTACHMENT,
                {"attachment_id": long_file.id, "start_char": start, "max_chars": 1000},
            )
            chunks.append(result["text"])
            start = result["next_start_char"]

        # Assert: whole lines per window, and nothing lost or repeated.
        self.assertTrue(all(chunk.endswith("\n") for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_read_bounds_a_window_by_its_encoded_size(self):
        # Arrange: CJK text JSON-escapes to six bytes per character.
        text = "研究" * 20_000
        wide = make_file(
            self.user, message=self.proposal.message, filename="z.txt", text=text
        )

        # Act
        result = self._call(
            READ_ATTACHMENT, {"attachment_id": wide.id, "max_chars": 40_000}
        )

        # Assert
        self.assertNotIn("error", result)
        self.assertLess(len(json.dumps(result)), MAX_TOOL_RESULT_BYTES)
        self.assertEqual(result["next_start_char"], len(result["text"]))

    def test_read_rejects_bad_bounds(self):
        cases = [
            {"start_char": -1},
            {"start_char": len(PDF_TEXT) + 1},
            {"max_chars": 40_001},
            {"max_chars": "10"},
        ]
        for bounds in cases:
            with self.subTest(bounds=bounds):
                # Act
                result = self._call(
                    READ_ATTACHMENT, {"attachment_id": self.proposal.id, **bounds}
                )

                # Assert
                self.assertIn("error", result)

    def test_read_accepts_a_numeric_string_id(self):
        # Act
        result = self._call(READ_ATTACHMENT, {"attachment_id": str(self.cv.id)})

        # Assert
        self.assertEqual(result["text"], CV_TEXT)

    def test_files_outside_the_conversation_are_unreachable(self):
        # Arrange
        conversations = AgentConversationService()
        other_chat = conversations.create(user=self.user, workflow="assistant_chat")
        elsewhere = make_file(
            self.user, message=conversations.add_human_message(other_chat, "hi")
        )
        unsent = make_file(self.user)
        failed = make_file(
            self.user,
            message=self.proposal.message,
            status=AgentFile.Status.FAILED,
        )

        for file in (elsewhere, unsent, failed):
            with self.subTest(file=file.id):
                # Act
                result = self._call(READ_ATTACHMENT, {"attachment_id": file.id})

                # Assert: the error names what the agent can read instead.
                self.assertIn("is not attached to this conversation", result["error"])
                self.assertIn(f'{self.cv.id} ("cv.txt")', result["error"])

    # -- search_attachment ------------------------------------------------

    def test_search_one_file_reports_pdf_pages(self):
        # Act
        budget = self._call(
            SEARCH_ATTACHMENT,
            {"attachment_id": self.proposal.id, "query": "sequencing budget"},
        )
        approach = self._call(
            SEARCH_ATTACHMENT,
            {"attachment_id": self.proposal.id, "query": "donors", "max_passages": 1},
        )

        # Assert
        top = budget["passages"][0]
        self.assertEqual(top["attachment_id"], self.proposal.id)
        self.assertIn("Budget justification", top["text"])
        self.assertEqual(top["pages"], "3")
        self.assertEqual(budget["match_count"], len(budget["passages"]))
        (passage,) = approach["passages"]
        self.assertIn("40 donors", passage["text"])
        self.assertIn(passage["pages"], ("2", "1-2"))

    def test_search_without_an_id_covers_every_attached_file(self):
        # Act
        result = self._call(SEARCH_ATTACHMENT, {"query": "CRISPR", "max_passages": 5})

        # Assert
        found = {passage["attachment_id"] for passage in result["passages"]}
        self.assertEqual(found, {self.proposal.id, self.cv.id})
        cv_passage = next(
            passage
            for passage in result["passages"]
            if passage["attachment_id"] == self.cv.id
        )
        self.assertIsNone(cv_passage["pages"])

    def test_search_validates_its_input(self):
        # Arrange
        empty_toolset = AttachmentToolset(
            conversation=AgentConversationService().create(user=self.user)
        )

        # Act
        blank = self._call(SEARCH_ATTACHMENT, {"query": "  "})
        too_long = self._call(SEARCH_ATTACHMENT, {"query": "x" * 501})
        no_files, _ = empty_toolset.as_toolset().dispatch(
            SEARCH_ATTACHMENT, {"query": "aims"}
        )

        # Assert
        self.assertEqual(blank["error"], "query is required")
        self.assertIn("500", too_long["error"])
        self.assertIn("No files are attached", no_files["error"])

    # -- manifest and activity ----------------------------------------------

    def test_manifest_names_each_file_the_agent_can_read(self):
        # Arrange
        AgentFile.objects.filter(id=self.proposal.id).update(
            page_count=3, text_truncated=True, filename='Aims "final".pdf'
        )
        files = list(
            AgentFile.objects.filter(id__in=[self.proposal.id, self.cv.id])
            .annotate(text_chars=Length("text"))
            .order_by("id")
        )

        # Act
        manifest = attachment_manifest(files)

        # Assert
        self.assertTrue(manifest.startswith("[The user attached these files"))
        self.assertIn(
            f'- attachment {self.proposal.id}: "Aims \\"final\\".pdf" (PDF, 3 pages, '
            f"{len(PDF_TEXT):,} characters, the rest of the file was too long "
            "to keep)",
            manifest,
        )
        self.assertIn(
            f'- attachment {self.cv.id}: "cv.txt" (text file, '
            f"{len(CV_TEXT)} characters)",
            manifest,
        )
        self.assertIsNone(attachment_manifest([]))

    def test_activity_shows_the_file_read_and_the_query_searched(self):
        # Arrange
        at = datetime(2026, 9, 29, tzinfo=UTC)
        events = [
            ToolCallEvent(
                tool=READ_ATTACHMENT,
                input={"attachment_id": self.proposal.id},
                started_at=at,
                finished_at=at,
                result={"filename": "grant.pdf", "text": PDF_TEXT},
            ),
            ToolCallEvent(
                tool=SEARCH_ATTACHMENT,
                input={"query": "budget"},
                started_at=at,
            ),
        ]

        # Act
        read, search = public_activity(
            events,
            execution_active=True,
            answer_published=False,
            published_answer=None,
        )

        # Assert
        self.assertEqual(read["label"], "Read an attached file")
        self.assertEqual(read["detail"], "grant.pdf")
        self.assertNotIn("text", read)
        self.assertEqual(search["label"], "Searched attached files")
        self.assertEqual(search["detail"], "budget")
        self.assertEqual(search["status"], "in_progress")
