import logging
import sys
from typing import Callable, Any
from unittest import TestCase
from unittest.mock import patch

from paper.summarizer import PaperSummarizer

logger = logging.getLogger()
logger.level = logging.DEBUG
stream_handler = logging.StreamHandler(sys.stdout)
logger.addHandler(stream_handler)


class PaperSummarizerTest(TestCase):
    @patch('openai.Completion')
    @patch('paper.models.Paper')
    def test_get_summary(self, Paper, Completion):
        # Arrange
        paper = Paper()
        paper.id = 1
        with open('paper/tests/test_data/pdf_file_extract_sample.html') as f:
            pdf_file_extract = f.read()
            paper.pdf_file_extract.read.return_value = pdf_file_extract

        # Expecting to split text into 4 chunks:
        responses = [
            # Summary for Chunk 1
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "text": "\n: Chunk 1 summary part 1."
                    }
                ],
            },
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "text": " Chunk 1 summary part 2."
                    }
                ],
            },
            # Summary for Chunk 2
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "text": "Chunk 2 summary."
                    }
                ],
            },
            # Summary for Chunk 3
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "text": "Chunk 3 summary."
                    }
                ],
            },
            # Summary for Chunk 4
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "text": "Chunk 4 summary."
                    }
                ],
            },
            # Summary of summaries
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "text": "Summary of summaries"
                    }
                ],
            }
        ]
        Completion.create.side_effect = responses

        # replace sentry.log_error with a mock
        fake_log_error: Callable[[Any], None] = lambda e: logger.info(e)
        with patch("utils.sentry.log_error", wraps=fake_log_error):
            # Act
            summarizer = PaperSummarizer(paper)
            summary = summarizer.get_summary()

        # Assert
        self.assertEqual("Summary of summaries", summary)
