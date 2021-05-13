def get_orcid_works(data):
    try:
        return data['activities-summary']['works']['group']
    except Exception as e:
        print(e)
    return []


def check_doi_in_works(doi, works):
    for work in works:
        work_doi = get_work_doi(work)
        if doi == work_doi:
            return True
    return False


def get_orcid_names(data):
    name = data['person']['name']
    first_name = name['given-names']['value']
    last_name = name['family-name']['value'] if name['family-name'] else ''
    return first_name, last_name


def get_work_doi(work):
    eids = work['external-ids']['external-id']
    for eid in eids:
        if eid['external-id-type'] == 'doi':
            return eid['external-id-value']
    return None
