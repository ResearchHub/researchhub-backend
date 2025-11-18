from typing import List, TypedDict


class SyncResult(TypedDict):
    success: bool
    synced: int
    failed: int
    errors: List[str]


class SyncResultWithSkipped(TypedDict):
    success: bool
    synced: int
    failed: int
    skipped: int
    errors: List[str]
