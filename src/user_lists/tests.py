# TODO:
#  - User can't modify/see/delete/create another user's list or list item
#  - Adding the same document to a list twice doesn't create duplicates
#  - Two lists can't have the same name
#  - Lists endpoint returns items with ≤ N queries (assert query count in a test for a typical size, e.g., 1 list + 10 items)
#  - Soft delete: after DELETE, the object does not appear in list endpoints.
#  - Lowercase: posting "PAPER" stores "paper"
