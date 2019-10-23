from summary.models import Summary


def build_summary_data(summary, paper_id, previous_summary_id):
    return {
        'summary': summary,
        'paper': paper_id,
        'previousSummaryId': previous_summary_id,
    }


def create_summary(summary, proposed_by, paper_id):
    return Summary.objects.create(
        summary=summary,
        proposed_by=proposed_by,
        paper_id=paper_id
    )
