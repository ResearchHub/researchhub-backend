import gzip
import json
import pandas as pd
import os
from datetime import datetime
from pathlib import Path
from unicodedata import normalize
from slugify import slugify
import secrets
import shutil

def check_has_enough_disk_space():
    """
    Check if the machine has enough disk space to continue.
    """
    # 5 GB
    min_free_space = 5 * 1024 * 1024 * 1024
    path_to_check = '/'

    total, used, free = shutil.disk_usage(path_to_check)

    total_in_gb = total / (1024 * 1024 * 1024)
    used_in_gb = used / (1024 * 1024 * 1024)
    free_in_gb = free / (1024 * 1024 * 1024)

    print("Disk space:")
    # Print with only 2 decimal places
    print(f"\tTotal: {total_in_gb:.2f} GB")
    print(f"\tUsed: {used_in_gb:.2f} GB")
    print(f"\tFree: {free_in_gb:.2f} GB")

    if free < min_free_space:
        print("Low disk space. Stopping the program.")
        exit()

def get_random_string(length=12):
    return secrets.token_urlsafe(length)

def get_year_month_from_data(data):
    """
    Extract the year and month from the paper's publication date.
    Returns None if the date is not within the past 5 years.
    """
    raw_pub_date = data.get('paper_publish_date', None)
    if raw_pub_date is None:
        print(f"Missing paper_publish_date: {data.get('doi', data.get('alternate_ids', None))}")
        return None, None
    
    pub_date = datetime.strptime(raw_pub_date, '%Y-%m-%d').date()
    cutoff_date = (datetime.now() - pd.DateOffset(years=5)).date()
    if pub_date < cutoff_date:
        return None, None
    return pub_date.year, pub_date.month

def format_raw_authors(raw_authors):
    for author in raw_authors:
        if "family" in author:
            first_name = author.pop("given", "")
            last_name = author.pop("family", "")

            author["first_name"] = first_name
            author["last_name"] = last_name
        elif "literal" in author:
            name = author.pop("literal", "")
            names = name.split(" ")
            first_name = names[0]
            last_name = names[-1]

            author["first_name"] = first_name
            author["last_name"] = last_name
        elif "author" in author:
            # OpenAlex Cleaning
            author.pop("author_position", None)
            author.pop("institutions", None)
            author.pop("raw_affiliation_string", None)

            author_data = author.pop("author")
            name = author_data.pop("display_name")
            open_alex_id = author_data.pop("id")
            names = name.split(" ")
            first_name = names[0]
            last_name = names[-1]

            author_data["open_alex_id"] = open_alex_id
            author_data["first_name"] = first_name
            author_data["last_name"] = last_name
            author.update(author_data)
        elif "name" in author:
            author.pop("authorId", None)
            name = author.pop("name", "")
            names = name.split(" ")
            first_name = names[0]
            last_name = names[-1]

            author["first_name"] = first_name
            author["last_name"] = last_name

    return raw_authors

def process_json_line(line):
    """
    Process and transform each JSON line to match the schema.
    Return a dictionary of transformed data.
    """
    try:
        data = json.loads(line)

        if data.get('type', data.get('publication_type', '')) != 'article':
            return "NOT_ARTICLE", "NOT_ARTICLE", "NOT_ARTICLE"

        pdf_url = None
        pdf_license = None

        best_oa_location = data.get('best_oa_location', {})
        primary_location = data.get('primary_location', {})

        if best_oa_location:
            pdf_url = best_oa_location.get('pdf_url')
            pdf_license = best_oa_location.get('license')

        if pdf_url is None and primary_location:
            pdf_url = primary_location.get('pdf_url')
            pdf_license = primary_location.get('license', pdf_license)

        raw_pub_date = data.get('publication_date', None)
        if raw_pub_date is None:
            raw_pub_year = data.get('publication_year', None)
            if raw_pub_year is None:
                print(f"Missing publication_date and publication_year: {data.get('id', data.get('doi', data.get('ids', None)))}")
                log_failed_line(line)
                return None, None, None
            pub_year = int(raw_pub_year)
            pub_date = datetime(pub_year, 1, 1).date()
            # format it like YYYY-MM-DD
            pub_date = pub_date.strftime('%Y-%m-%d')
        else:
            pub_date = datetime.strptime(raw_pub_date, '%Y-%m-%d').date()
            pub_date = pub_date.strftime('%Y-%m-%d')

        if primary_location is None:
            if best_oa_location is not None:
                primary_location = best_oa_location
            else:
                primary_location = {}
    
        source = primary_location.get("source", {})
        if source is None:
            source = {}
        external_source = source.get("display_name", None) or source.get("name", None) or source.get("publisher", None)
        url = primary_location.get("landing_page_url", None)
        oa = data.get("open_access", {})
        if oa is None:
            oa = {}
        raw_title = data.get("title", "") or ""
        title = normalize("NFKD", raw_title)
        raw_authors = data.get("authorships", [])
        concepts = data.get("concepts", [])

        if pdf_license is None:
            pdf_license = primary_location.get("license", None)
        if pdf_license is None:
            pdf_license = data.get("license", None)

        paper_data = {
            'title': title,
            'paper_publish_date': pub_date,
            'doi': data.get('doi', data.get('ids', {}).get('doi', '')),
            'url': url,
            'publication_type': data.get('type', ''),
            'paper_title': title,
            'pdf_url': pdf_url,
            'retrieved_from_external_source': True,
            'is_public': True,
            'is_removed': False,
            'external_source': external_source,
            'pdf_license': pdf_license,
            'raw_authors': json.dumps(format_raw_authors(raw_authors)),
            'discussion_count': 0,
            'alternate_ids': json.dumps(data.get('ids', {})),
            'slug': slugify(title),
            # if the slug already exists in the db we can fallback to this alternate slug
            # this is the same pattern we use in the backend.
            'alt_slug': slugify(title) + '-' + get_random_string(length=32),
            'paper_type': 'REGULAR',
            'completeness': 'INCOMPLETE',
            'open_alex_raw_json': json.dumps(data),
            'citations': data.get('cited_by_count', 0),
            'downloads': 0,
            'twitter_mentions': 0,
            'views': 0,
            'is_open_access': oa.get('is_oa', False),
            'oa_status': oa.get('oa_status', None),
        }

        unified_document_data = {
            'document_type': 'PAPER',
            'published_date': pub_date,
            # these fields are so that we can associate the paper and unified_document after
            # and set paper_paper.unified_document_id correctly.
            'paper_doi': paper_data['doi'],
            'paper_url': paper_data['url'],
        }

        concepts_data = []
        for concept in concepts:
            concepts_data.append({
                'openalex_id': concept.get('id', ''),
                'display_name': concept.get('display_name', ''),
                'level': concept.get('level', 0),
                'score': concept.get('score', 0),
                # these fields are so that we can associate the paper and concept after
                # and set unified_document.concepts and unified_document.hubs
                'paper_doi': paper_data['doi'],
                'paper_url': paper_data['url'],
            })

        return paper_data, unified_document_data, concepts_data
    
    except Exception as e:
        print(f"Error processing line: {e}")
        log_failed_line(line)
        return None, None, None

def write_to_csv(data, name, year, month):
    """
    Write the data to a CSV file named by year and month.
    Append if the file already exists.
    """
    # Expanding the tilde to the user's home directory
    base_path = os.path.expanduser("~/openalex-snapshot")
    filename = f"{base_path}/{year}_{name}.csv"

    # Ensure base directory exists
    os.makedirs(base_path, exist_ok=True)

    data.to_csv(filename, mode='a', header=not os.path.exists(filename), index=False)

def log_failed_line(line):
    """
    Write the failed line to a file.
    """
    # Expanding the tilde to the user's home directory
    base_path = os.path.expanduser("~/openalex-snapshot")
    filename = f"{base_path}/failed_lines.jsonl"

    # Ensure base directory exists
    os.makedirs(base_path, exist_ok=True)

    with open(filename, 'a') as f:
        f.write(line)

def write_log(log_data):
    """
    Write the log data to JSON lines file.
    """
    # Expanding the tilde to the user's home directory
    base_path = os.path.expanduser("~/openalex-snapshot")
    filename = f"{base_path}/log.jsonl"

    # Ensure base directory exists
    os.makedirs(base_path, exist_ok=True)

    with open(filename, 'a') as f:
        f.write(json.dumps(log_data) + '\n')

def process_file(file_path):
    """
    Process a given gzipped JSONL file.
    """
    papers_by_month = {}
    unified_documents_by_month = {}
    concepts_by_month = {}
    log_data = {
        "file_path": str(file_path),
        "processed": 0,
        "missing_data": 0,
        "not_article": 0,
        "invalid_date": 0,
    }
    with gzip.open(file_path, 'rt', encoding='utf-8') as f:
        for line in f:
            paper_data, unified_document_data, concepts_data = process_json_line(line)
            if paper_data is None or unified_document_data is None or concepts_data is None:
                log_data['missing_data'] = log_data.get('missing_data', 0) + 1
                continue
            if paper_data == "NOT_ARTICLE":
                log_data['not_article'] = log_data.get('not_article', 0) + 1
                continue

            year, month = get_year_month_from_data(paper_data)
            if year is None or month is None:
                log_data['invalid_date'] = log_data.get('invalid_date', 0) + 1
                continue

            key = f"{year}_{month}"
            if key not in papers_by_month:
                papers_by_month[key] = []
            papers_by_month[key].append(paper_data)
            if key not in unified_documents_by_month:
                unified_documents_by_month[key] = []
            unified_documents_by_month[key].append(unified_document_data)
            if key not in concepts_by_month:
                concepts_by_month[key] = []
            concepts_by_month[key].extend(concepts_data)

            log_data['processed'] = log_data.get('processed', 0) + 1

    # Write Papers
    for key, data_list in papers_by_month.items():
        year, month = key.split('_')
        df = pd.DataFrame(data_list)
        write_to_csv(df, 'paper_paper', int(year), int(month))

    # Write UnifiedDocuments
    for key, data_list in unified_documents_by_month.items():
        year, month = key.split('_')
        df = pd.DataFrame(data_list)
        write_to_csv(df, 'researchhub_unified_document', int(year), int(month))

    # Write Concepts
    for key, data_list in concepts_by_month.items():
        year, month = key.split('_')
        df = pd.DataFrame(data_list)
        write_to_csv(df, 'tag_concept', int(year), int(month))

    # Write log
    write_log(log_data)

    print(f"Processed {log_data['processed']} entries")
    print(f"\t{log_data['missing_data']} entries missing data")
    print(f"\t{log_data['not_article']} entries not articles")
    print(f"\t{log_data['invalid_date']} entries with invalid date")

    print(f"Deleting {file_path}")
    os.remove(file_path)

def main():
    base_snapshot_path = Path(os.path.expanduser("~/openalex-snapshot"))
    
    # Iterate over all directories starting with 'updated_date'
    for date_folder in base_snapshot_path.glob("updated_date*"):
        print(f"\nProcessing folder: {date_folder}")
        
        # Process each gzipped file in the current date folder
        for file_path in date_folder.glob("part_*.gz"):
            # Before processing each file, check if there's enough disk space
            check_has_enough_disk_space()

            print(f"\nProcessing file: {file_path}")
            process_file(file_path)

if __name__ == "__main__":
    main()
