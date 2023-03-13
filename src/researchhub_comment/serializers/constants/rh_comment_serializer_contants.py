RH_COMMENT_FIELDS = [
    "children",
    "comment_content_json",
    "comment_content_type",
    "context_title",
    "is_edited",
    "created_date",
    "updated_date",
    "parent_id",  # expose only the id. No need to display entire instance
    "thread_id",
]
RH_COMMENT_READ_ONLY_FIELDS = [
    "children",
    "is_edited",
    "created_date",
    "updated_date",
    "parent_id",  # expose only the id. No need to display entire instance
    "thread_id",
]
