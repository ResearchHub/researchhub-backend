def check_thread_in_papers(thread, papers):
    return thread.parent in papers


def check_reply_in_threads(reply, threads):
    comment = reply.get_comment_of_reply()
    return check_comment_in_threads(comment, threads)


def check_reply_in_comments(reply, comments):
    comment = reply.get_comment_of_reply()
    return comment in comments


def check_comment_in_threads(comment, threads):
    return comment.parent in threads
