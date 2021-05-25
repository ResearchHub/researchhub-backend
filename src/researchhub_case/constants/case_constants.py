ALLOWED_VALIDATION_ATTEMPT_COUNT = 10
AUTHOR_CLAIM = 'AUTHOR_CLAIM'

APPROVED = 'APPROVED'
# "Denied" signifies moderators manually denying the request
DENIED = 'DENIED'
INITIATED = 'INITIATED'
# Invalidations occurs through the system such as too many attempts
INVALIDATED = 'INVALIDATED'
"""
  Nullified signifies that the author was
  claimed by someone else during process
"""
NULLIFIED = 'NULLIFIED'
OPEN = 'OPEN'


AUTHOR_CLAIM_CASE_STATUS = [
    (APPROVED, APPROVED),
    (DENIED, DENIED),
    (INITIATED, INITIATED),
    (INVALIDATED, INVALIDATED),
    (NULLIFIED, NULLIFIED),
    (OPEN, OPEN),
]

RH_CASE_TYPES = [
    (AUTHOR_CLAIM, AUTHOR_CLAIM)
]
