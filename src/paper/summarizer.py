import re
from typing import Optional, List

import openai
import xmltodict
from celery.utils.log import get_task_logger
from paper.models import Paper
from researchhub.settings import keys

logger = get_task_logger(__name__)


class PaperSummarizer:
    """
    Uses the OpenAI API to generate summaries for a given paper.
    """

    TOKEN_LENGTH = 4
    """
    The average OpenAI token for the English language is 4 characters.
    See more: https://help.openai.com/en/articles/4936856-what-are-tokens-and-how-to-count-them 
    """

    OPENAI_MAX_TOKENS = {
        "text-davinci-003": 4097,
        "text-davinci-002": 4097
    }
    """
    Each model used for the text completion, has a maximum number of allowed tokens. This includes the tokens in the 
    response. 

    See more: 
      * https://platform.openai.com/docs/models/gpt-3-5 
      * https://help.openai.com/en/articles/4936856-what-are-tokens-and-how-to-count-them 
    """

    def __init__(self, paper: Paper):
        self._paper: Paper = paper

    def get_summary(self, openai_model: str = "text-davinci-003", max_response_tokens: int = 120) -> Optional[str]:
        """
        Generates a summary for the paper using the given OpenAI model and response size.
        First, splits the text of the paper into chunks of a length allowable by the selected OpenAI model. Then, calls
        the OpenAI API for each of the chunks, which generates a  summary for each of them. The concatenation of the
        summaries of all chunks is sent to the OpenAI API one last time to generate the final result.
        See more: https://platform.openai.com/docs/api-reference/completions/create

        :param openai_model: The model used for generating the summary. The list of supported models is
                             'text-davinci-003' (default), and 'text-davinci-002'. See details about each model at:
                             https://platform.openai.com/docs/models/gpt-3-5
        :param max_response_tokens: The maximum number of tokens to generate in the summary. Defaults to 120. See more:
                                    https://platform.openai.com/docs/api-reference/completions/create#completions/create-max_tokens
        :return: a string representing the summary of the paper, if the generation succeeds, or None otherwise
        """

        try:
            logger.info(
                f"Using model {openai_model} to generate a summary of no more than "
                f"{max_response_tokens} tokens from OpenAI")
            html_content = self._paper.pdf_file_extract.read()
            paragraphs = PaperSummarizer._extract_paragraphs_from_html_article(html_content)

            if paragraphs is None or len(paragraphs) == 0:
                logger.warn(f"Unable to extract paragraphs from paper {self._paper.id}.")
                return None

            logger.info(f"Extracted {len(paragraphs)} paragraphs from paper {self._paper.id}.")

            # Compute the maximum chunk length that OpenAI will allow. Since the number of tokens per text length is an
            # approximation, we use MAX_TOKENS - max_response_tokens * 2 as the maximum number of tokens per
            # request to leave some legroom.
            max_request_tokens = PaperSummarizer.OPENAI_MAX_TOKENS[openai_model] - max_response_tokens * 2
            max_chunk_length = max_request_tokens * PaperSummarizer.TOKEN_LENGTH

            chunks = []
            current_chunk = ""

            # We attempt to build chunks from full paragraphs (i.e. not split a paragraph among chunks), so they make
            # more sense to the OpenAI model.
            for p in paragraphs:
                if len(current_chunk) + len(p) > max_chunk_length:
                    if len(current_chunk) > 0:
                        chunks.append(current_chunk)
                    current_chunk = p
                    # If a single paragraph is larger than the allowed chunk length, then we split it into smaller bits.
                    while len(current_chunk) > max_chunk_length:
                        chunks.append(current_chunk[0:max_chunk_length])
                        current_chunk = current_chunk[max_chunk_length:]
                    continue
                current_chunk = f"{current_chunk}\n{p}"
            if len(current_chunk) > 0:
                chunks.append(current_chunk)

            logger.info(
                f"Splitting OpenAI requests into {len(chunks)} requests of {max_chunk_length} or fewer characters")

            summary_parts = []
            for chunk in chunks:
                summary_part = ""
                try:
                    summary_part = PaperSummarizer._generate_openai_summary(chunk, openai_model, max_response_tokens)
                except Exception as e:
                    logger.warn(e)

                if summary_part != "":
                    summary_parts.append(summary_part)

            if len(summary_parts) == 0:
                logger.warn(f"Failed to extract OpenAI summary for the paper {self._paper.id}")
                return None

            summary = ""
            if len(summary_parts) > 1:
                # If we have multiple summaries, we'll make one final call to openai, to create the summary of all
                # summaries:
                concatenated = "\n".join(summary_parts)
                summary = PaperSummarizer._generate_openai_summary(
                    concatenated[0:max_chunk_length], openai_model, max_response_tokens)
            else:
                summary = summary_parts[0]

            logger.info(f"A summary of length {len(summary)} generated successfully.")

            # Remove non-alphanumeric characters from the beginning of the summary
            return re.sub(r"^\W+", "", summary)

        except Exception as e:
            logger.warn(f"There was an error generating the OpenAI summary: {e}")
        return None

    @staticmethod
    def _extract_paragraphs_from_html_article(html_content: str) -> Optional[List[str]]:
        """
        Takes the html content generated by converting the pdf via CERMINE, and extracts all titles and paragraphs
        from each of the article sections. The input is in NLM JATS format, as described at
        http://jats.nlm.nih.gov/archiving/tag-library/1.1/chapter/nfd-body-and-sec.html

        :return: a list of strings representing the section titles and paragraphs, or None if the document cannot be
                 parsed
        """
        try:
            doc = xmltodict.parse(html_content)

            # Get the article sections, as generated by CERMINE using the NLM JATS format.
            sections = doc["html"]["body"]["article"]["sec"]
            if sections is None:
                logger.warn("Document has no sections")
                return None

            paragraphs = []

            if isinstance(sections, list):
                for sec in sections:
                    paragraphs.extend(PaperSummarizer._extract_flattened_paragraphs_from_section(sec))
            elif isinstance(sections, dict):
                paragraphs.extend(PaperSummarizer._extract_flattened_paragraphs_from_section(sections))
            else:
                raise Exception("Document has a section that's not dict or list")

            return paragraphs

        except Exception as e:
            logger.warn(e)
            return None

    @staticmethod
    def _extract_flattened_paragraphs_from_section(section: dict) -> List[str]:
        """
        Extracts a flattened list of all titles and paragraphs from the given article section hierarchy. See format at
        http://jats.nlm.nih.gov/archiving/tag-library/1.1/chapter/nfd-sec.html

        :return: a list of strings representing the titles and paragraphs in the given section
        """
        result = []

        # Iterate over title, paragraphs, and subsections.
        for item in section.items():
            key, value = item
            if key == "title":
                result.append(value.strip())
                continue
            elif key == "p":
                # paragraphs
                if isinstance(value, str):
                    result.append(value.strip())
                else:
                    # isinstance(value, list)
                    for paragraph in value:
                        if isinstance(paragraph, str):
                            result.append(paragraph)
                        else:
                            # isinstance(paragraph, dict)
                            text = paragraph.get("#text")
                            if text is not None:
                                result.append(text.strip())
                continue
            elif key == "sec":
                # subsections
                if isinstance(value, dict):
                    result.extend(PaperSummarizer._extract_flattened_paragraphs_from_section(value))
                else:
                    # isinstance(value, list):
                    for section in value:
                        result.extend(PaperSummarizer._extract_flattened_paragraphs_from_section(section))
                continue
            else:
                continue

        return result

    @staticmethod
    def _generate_openai_summary(chunk: str, model: str, max_response_tokens: int) -> str:
        """
        Calls OpenAI to get the TL;DR completion summary for the given chunk of text.
        See more: https://platform.openai.com/docs/api-reference/completions/create

        :return: a string representing the summary of the given chunk of text
        """
        openai.organization = keys.OPENAI_ORG
        openai.api_key = keys.OPENAI_KEY

        summary = ""
        logger.info(f"Length of chunk sent to OpenAI: {len(chunk)}")

        # We make multiple requests to the OpenAI API, until all the response has been fetched. This is assessed by
        # checking the 'finish_reason' response parameter, which should be 'stop' when the response is complete.
        # See https://platform.openai.com/docs/guides/chat/response-format
        while True:
            try:
                response = openai.Completion.create(
                    model=model,
                    prompt=f"{chunk}\n\nTl;dr{summary}",
                    temperature=0.7,
                    max_tokens=max_response_tokens,
                    top_p=1.0,
                    frequency_penalty=0.0,
                    presence_penalty=1
                )

                choice = response.get("choices")[0]
                text = None
                finish_reason = None
                if choice is not None:
                    text = choice.get("text")
                    finish_reason = choice.get("finish_reason")

                if text is None or text == "":
                    break

                summary = summary + text
                if finish_reason is None or finish_reason == "stop":
                    break

                if len(summary) > max_response_tokens * PaperSummarizer.TOKEN_LENGTH * 2:
                    # To prevent an infinite loop, we make sure that if the summary has reached twice the expected
                    # length, we stop.
                    summary = summary + "..."
                    break

            except Exception as e:
                logger.warn(f"There was an error extracting the OpenAI summary for chunk of text '{chunk}': {e}")
                # If an error has occurred, but we've already fetched some content, then we append "..." to our partial
                # result and use it like that.
                if len(summary) > 0:
                    summary = summary + "..."
                break

        return summary
