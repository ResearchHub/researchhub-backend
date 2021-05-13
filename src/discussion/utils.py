def get_paper_id_from_path(request):
    PAPER = 2
    paper_id = None
    path_parts = request.path.split('/')
    if path_parts[PAPER] == 'paper':
        try:
            paper_id = int(path_parts[PAPER + 1])
        except ValueError:
            print('Failed to get paper id')
    return paper_id


def get_thread_id_from_path(request):
    DISCUSSION = 4
    thread_id = None
    path_parts = request.path.split('/')
    if path_parts[DISCUSSION] == 'discussion':
        try:
            thread_id = int(path_parts[DISCUSSION + 1])
        except ValueError:
            print('Failed to get discussion id')
    return thread_id


def get_comment_id_from_path(request):
    COMMENT = 6
    comment_id = None
    path_parts = request.path.split('/')
    if path_parts[COMMENT] == 'comment':
        try:
            comment_id = int(path_parts[COMMENT + 1])
        except ValueError:
            print('Failed to get comment id')
    return comment_id
