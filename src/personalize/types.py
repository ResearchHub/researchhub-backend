from typing import TypedDict


class SyncResult(TypedDict):
    success: bool
    synced: int
    failed: int
    errors: list[str]


class SyncResultWithSkipped(TypedDict):
    success: bool
    synced: int
    failed: int
    skipped: int
    errors: list[str]


class PersonalizeEvent(TypedDict, total=False):
    eventId: str
    eventType: str
    eventValue: float
    impression: list[str]
    itemId: str
    recommendationId: str
    properties: str
    sentAt: int
