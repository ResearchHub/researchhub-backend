from django.core.cache import cache

LOCK_TIMEOUT = 3600


def name(lock_key: str) -> str:
    """
    Get a lock key including the specified string.
    """
    return f"lock:{lock_key}"


def acquire(lock_key: str, timeout: int = LOCK_TIMEOUT) -> bool:
    """
    Acquire a lock using the specified name.
    """
    return cache.add(lock_key, True, timeout)


def extend(lock_key: str, timeout: int = LOCK_TIMEOUT) -> bool:
    """
    Extend the lock using the specified name.
    """
    return cache.touch(lock_key, timeout)


def release(lock_key: str) -> None:
    """
    Release the lock using the specified name.
    """
    cache.delete(lock_key)
