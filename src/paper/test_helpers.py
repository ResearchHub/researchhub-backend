from .models import Paper


class TestData:
    paper_title = ('Messrs Moony, Wormtail, Padfoot, and Prongs Purveyors of'
                   ' Aids to Magical Mischief-Makers are proud to present THE'
                   ' MARAUDER\'S MAP'
                   )
    paper_publish_date = '1990-10-01'


def create_paper(
    title=TestData.paper_title,
    paper_publish_date=TestData.paper_publish_date,
    uploaded_by=None
):
    return Paper.objects.create(
        title=title,
        paper_publish_date=paper_publish_date,
        uploaded_by=uploaded_by
    )
