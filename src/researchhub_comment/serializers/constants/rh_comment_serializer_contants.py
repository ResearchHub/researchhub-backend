RH_COMMENT_FIELDS = [
    "children",
    "comment_content_json",
    "comment_content_type",
    "context_title",
    "created_date",
    "id",
    "is_edited",
    "parent_id",  # expose only the id. No need to display entire instance
    "thread_id",
    "updated_date",
]
RH_COMMENT_READ_ONLY_FIELDS = [
    "children",
    "created_date",
    "id",
    "is_edited",
    "parent_id",  # expose only the id. No need to display entire instance
    "thread_id",
    "updated_date",
]
