from paper.tests.helpers import create_paper
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from user.tests.helpers import create_random_default_user


def create_rh_comment(
    paper=None,
    post=None,
    created_by=None,
    title="Thread Title",
    text="This is a thread.",
    parent=None,
):
    if created_by is None:
        created_by = create_random_default_user("default_rh_comment")
    if paper is None and post is None:
        paper = create_paper(uploaded_by=created_by)

    thread = RhCommentThreadModel.objects.create(
        content_object=paper or post,
        created_by=created_by,
        updated_by=created_by,
    )
    comment = RhCommentModel.objects.create(
        comment_content_json={"text": text},
        context_title=title,
        thread=thread,
        created_by=created_by,
        updated_by=created_by,
        parent=parent,
    )
    return comment
