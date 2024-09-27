CREATED_LOCATIONS = {
    "FEED": "FEED",
    "HUB": "HUB",
    "PAPER": "PAPER",
    "PROGRESS": "PROGRESS",
}

CREATED_LOCATION_CHOICES = [
    (CREATED_LOCATIONS["FEED"], CREATED_LOCATIONS["FEED"]),
    (CREATED_LOCATIONS["HUB"], CREATED_LOCATIONS["HUB"]),
    (CREATED_LOCATIONS["PAPER"], CREATED_LOCATIONS["PAPER"]),
    (CREATED_LOCATIONS["PROGRESS"], CREATED_LOCATIONS["PROGRESS"]),
]


def get_document_id_from_path(request):
    DOCUMENT_INDEX = 2
    document_id = None
    path_parts = request.path.split("/")

    if path_parts[DOCUMENT_INDEX] in (
        "paper",
        "post",
        "hypothesis",
        "citation",
        "peer_review",
        "researchhub_post",
    ):
        try:
            document_id = int(path_parts[DOCUMENT_INDEX + 1])
        except ValueError:
            print("Failed to get document id")
    return document_id
