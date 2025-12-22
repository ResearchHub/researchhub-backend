from paper.tasks.embedding_tasks import (  # noqa: F401
    generate_embeddings_batch,
    generate_paper_embedding,
)
from paper.tasks.figure_tasks import (  # noqa: F401
    celery_extract_pdf_preview,
    create_pdf_screenshot,
    extract_pdf_figures,
    generate_thumbnail_for_figure,
    select_primary_image,
)
from paper.tasks.tasks import (  # noqa: F401
    censored_paper_cleanup,
    create_download_url,
    download_pdf,
)
