def get_paper_id_from_path(request):
    PAPER_INDEX = 2
    paper_id = None
    path_parts = request.path.split('/')
    if path_parts[PAPER_INDEX] == 'paper':
        try:
            paper_id = int(path_parts[PAPER_INDEX + 1])
        except ValueError:
            print('Failed to get paper id')
    return paper_id
