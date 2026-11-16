"""Observed tool outcomes, independent of how a model describes its work."""

from dataclasses import dataclass, field


@dataclass
class RunToolMetrics:
    tool_calls: int = 0
    tool_errors: int = 0
    note_edit_attempts: int = 0
    note_edits_saved: int = 0
    note_edit_errors: int = 0
    note_edit_recoveries: int = 0
    _failed_notes: set[str] = field(default_factory=set)

    def observe(self, name: str, arguments: dict, result: dict) -> None:
        self.tool_calls += 1
        failed = "error" in result
        self.tool_errors += int(failed)
        if name != "edit_note":
            return
        self.note_edit_attempts += 1
        note_id = (
            str(arguments.get("note_id")) if isinstance(arguments, dict) else "None"
        )
        if failed or result.get("saved") is not True:
            self.note_edit_errors += 1
            self._failed_notes.add(note_id)
        else:
            self.note_edits_saved += 1
            if note_id in self._failed_notes:
                self.note_edit_recoveries += 1
                self._failed_notes.remove(note_id)

    def metadata(self) -> dict:
        if not self.note_edit_attempts:
            outcome = "not_attempted"
        elif self._failed_notes:
            outcome = "partially_saved" if self.note_edits_saved else "failed"
        else:
            outcome = "saved"
        return {
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "note_edit_attempts": self.note_edit_attempts,
            "note_edits_saved": self.note_edits_saved,
            "note_edit_errors": self.note_edit_errors,
            "note_edit_recoveries": self.note_edit_recoveries,
            "unresolved_note_edit_errors": len(self._failed_notes),
            "note_edit_outcome": outcome,
        }
