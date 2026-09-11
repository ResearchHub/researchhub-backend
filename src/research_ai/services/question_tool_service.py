"""Question tool shared by notebook and assistant chat."""

from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import UserInputRequest

MAX_QUESTION_CHARS = 2000
MAX_OPTION_CHARS = 200
MAX_OPTIONS = 5
ASK_QUESTION = "ask_question"


def _ask_question(args: dict) -> dict:
    if not isinstance(args, dict) or set(args) - {"question", "options"}:
        return {"error": "Provide question and optional options only."}
    question = args.get("question")
    if (
        not isinstance(question, str)
        or not 1 <= len(question.strip()) <= MAX_QUESTION_CHARS
    ):
        return {
            "error": f"question must be 1–{MAX_QUESTION_CHARS} nonblank characters."
        }
    options = args.get("options", [])
    if not isinstance(options, list) or len(options) not in (
        0,
        *range(2, MAX_OPTIONS + 1),
    ):
        return {"error": f"Provide no options or 2–{MAX_OPTIONS} options."}
    if any(
        not isinstance(option, str) or not 1 <= len(option.strip()) <= MAX_OPTION_CHARS
        for option in options
    ):
        return {
            "error": f"Each option must be 1–{MAX_OPTION_CHARS} nonblank characters."
        }
    options = [option.strip() for option in options]
    if len({option.casefold() for option in options}) != len(options):
        return {"error": "Options must be distinct."}
    return UserInputRequest(question.strip(), options).as_dict()


def build_question_tool() -> Tool:
    return Tool(
        name=ASK_QUESTION,
        description=(
            "Ask the user one focused question when missing information or a "
            "decision is needed to proceed. Optional choices are suggestions; "
            "the user can always reply in their own words. Call this tool alone. "
            "It ends this run immediately; the answer arrives as the next human "
            "message. Do not guess an answer or perform dependent actions first."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_QUESTION_CHARS,
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_OPTION_CHARS,
                    },
                    "maxItems": MAX_OPTIONS,
                    "uniqueItems": True,
                    "description": "Omit for free text, or supply 2–5 short choices.",
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        handler=_ask_question,
        requires_user_input=True,
    )
