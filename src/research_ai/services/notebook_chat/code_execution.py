"""Bounded, explicit public fields for provider-managed code execution.

Code and readable stdout are plain text for an expandable UI, never markup to
execute. Opaque output, file identifiers, and raw provider errors stay private.
"""

from research_ai.services.agent_persistence.activity import ToolCallEvent

CODE_EXECUTION_TOOLS = frozenset({"code_execution", "bash_code_execution"})
MAX_CODE_CHARS = 12_000
MAX_OUTPUT_CHARS = 2_000

_ERROR_SUMMARIES = {
    "execution_time_exceeded": "Execution timed out.",
    "unavailable": "Code execution is temporarily unavailable.",
    "container_expired": "The code execution session expired.",
    "too_many_requests": "Code execution is temporarily busy.",
}


def public_code_execution(event: ToolCallEvent) -> tuple[dict, str | None]:
    """Return selected execution fields and a short outcome summary, if known."""
    details = {}
    code_field = "command" if event.tool == "bash_code_execution" else "code"
    code = event.input.get(code_field)
    if isinstance(code, str) and code.strip():
        details["code"] = code[:MAX_CODE_CHARS]
        details["code_truncated"] = len(code) > MAX_CODE_CHARS

    if not event.completed:
        return details, None
    result = (event.result or {}).get("content")
    if not isinstance(result, dict):
        return details, "Code execution failed." if event.is_error else None

    return_code = result.get("return_code")
    if type(return_code) is int:
        details["return_code"] = return_code
    outputs = result.get("content")
    if isinstance(outputs, list):
        details["output_count"] = len(outputs)
    # An encrypted result must never be treated as readable, even if an
    # unexpected stdout field accompanies it.
    if result.get("type") != "encrypted_code_execution_result":
        stdout = result.get("stdout")
        if isinstance(stdout, str) and stdout.strip():
            details["output"] = stdout[:MAX_OUTPUT_CHARS]
            details["output_truncated"] = len(stdout) > MAX_OUTPUT_CHARS

    if event.is_error:
        error_code = result.get("error_code")
        if isinstance(error_code, str) and error_code in _ERROR_SUMMARIES:
            summary = _ERROR_SUMMARIES[error_code]
        elif type(return_code) is int and return_code != 0:
            summary = f"Code exited with error (exit code {return_code})."
        else:
            summary = "Code execution failed."
    elif type(return_code) is int and return_code == 0:
        summary = "Code finished successfully."
        count = details.get("output_count", 0)
        if count:
            summary += f" Produced {count} output item{'s' if count != 1 else ''}."
    else:
        summary = None
    return details, summary
