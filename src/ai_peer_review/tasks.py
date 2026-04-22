from ai_peer_review.services.proposal_review_service import run_proposal_review
from ai_peer_review.services.rfp_summary_service import run_rfp_summary
from researchhub.celery import app


@app.task
def process_proposal_review_task(review_id: int):

    run_proposal_review(review_id)


@app.task
def process_rfp_summary_task(rfp_summary_id: int):

    run_rfp_summary(rfp_summary_id)
