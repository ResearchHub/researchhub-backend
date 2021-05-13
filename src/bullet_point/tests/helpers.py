from bullet_point.models import BulletPoint
from paper.tests.helpers import create_paper
from user.tests.helpers import create_random_default_user


class TestData:
    text = {'text': 'This is a bullet point'}
    plain_text = 'This is a bullet point.'


def create_bullet_point(
    paper=None,
    created_by=None,
    text=TestData.text,
    plain_text=TestData.plain_text
):
    """Returns a newly created Bullet Point.

    Arguments:
        paper (Paper)
        created_by (User)
        text (str)
        plain_text (json)
    """
    if paper is None:
        paper = create_paper()
    if created_by is None:
        created_by = create_random_default_user('bullet_point')
    bullet_point = BulletPoint.objects.create(
        paper=paper,
        created_by=created_by,
        text=text,
        plain_text=plain_text
    )
    return bullet_point
