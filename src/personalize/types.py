from typing import List, Optional, TypedDict


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


class PersonalizeEvent(TypedDict, total=False):
    eventId: str
    eventType: str
    eventValue: float
    impression: List[str]
    itemId: str
    recommendationId: str
    properties: str
    sentAt: int
