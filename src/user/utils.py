def merge_author_profiles(source, target):
    # Remap papers
    for paper in source.authored_papers.all():
        paper.authors.remove(source)
        paper.authors.add(target)
        paper.save()

    target.save()
    source.delete()
    return target
