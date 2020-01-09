from discussion.models import Comment, Reply


def check_thread_in_papers(thread, papers):
    return thread.parent in papers


def check_reply_in_threads(reply, threads):
    comment = get_comment_of_reply(reply)
    return check_comment_in_threads(comment, threads)


def check_reply_in_comments(reply, comments):
    comment = get_comment_of_reply(reply)
    return comment in comments


def check_comment_in_threads(comment, threads):
    return comment.parent in threads


def get_comment_of_reply(parent):
    if isinstance(parent, Reply):
        return get_comment_of_reply(parent.parent)
    elif isinstance(parent, Comment):
        return parent
    else:
        raise TypeError(f'Unsupported {type(parent)}')
