"""
bioRxiv/medRxiv API response fixtures for testing
"""

import json

# Sample bioRxiv API response
BIORXIV_API_RESPONSE = {
    "messages": [
        {
            "status": "ok",
            "interval": "2024-01-01/2024-01-02",
            "cursor": 0,
            "count": 2,
            "total": "156",
        }
    ],
    "collection": [
        {
            "doi": "10.1101/2024.01.01.123456",
            "title": "Single-cell RNA sequencing reveals novel cell types in mouse brain",
            "authors": "Smith, Jane A.; Johnson, Robert B.; Lee, Maria C.",
            "author_corresponding": "Jane A. Smith",
            "author_corresponding_institution": "Harvard Medical School",
            "date": "2024-01-01",
            "version": "1",
            "type": "new",
            "license": "cc_by",
            "category": "neuroscience",
            "jatsxml": "https://www.biorxiv.org/content/10.1101/2024.01.01.123456v1.source.xml",
            "abstract": "Single-cell RNA sequencing (scRNA-seq) has revolutionized our understanding of cellular heterogeneity. Here we present a comprehensive atlas of mouse brain cell types identified through scRNA-seq of over 100,000 cells. We identify 15 previously unknown neuronal subtypes and characterize their spatial distribution, gene expression profiles, and potential functions. Our findings provide new insights into brain organization and establish a resource for future neuroscience research.",
            "published": "NA",
            "server": "biorxiv",
        },
        {
            "doi": "10.1101/2024.01.01.234567",
            "title": "CRISPR-Cas9 screening identifies essential genes for cancer cell survival",
            "authors": "Wilson, David; Martinez, Elena; Thompson, James K.; Anderson, Sarah",
            "author_corresponding": "David Wilson",
            "author_corresponding_institution": "MIT",
            "date": "2024-01-01",
            "version": "2",
            "type": "new version",
            "license": "cc_no",
            "category": "cancer biology",
            "jatsxml": "https://www.biorxiv.org/content/10.1101/2024.01.01.234567v2.source.xml",
            "abstract": "Understanding genetic dependencies in cancer cells is crucial for identifying therapeutic targets. We performed genome-wide CRISPR-Cas9 screens in 50 cancer cell lines to identify essential genes. Our analysis reveals both pan-cancer dependencies and lineage-specific vulnerabilities. We validate several novel targets using orthogonal approaches and demonstrate their potential as drug targets. This resource provides a comprehensive map of cancer dependencies.",
            "published": "10.1038/s41586-024-12345",
            "server": "biorxiv",
        },
    ],
}

# Sample medRxiv API response
MEDRXIV_API_RESPONSE = {
    "messages": [
        {
            "status": "ok",
            "interval": "2024-01-01/2024-01-02",
            "cursor": 0,
            "count": 2,
            "total": "89",
        }
    ],
    "collection": [
        {
            "doi": "10.1101/2024.01.01.345678",
            "title": "Effectiveness of COVID-19 vaccines against Omicron variant: A systematic review and meta-analysis",
            "authors": "Chen, Wei; Kumar, Raj; Brown, Jennifer; White, Michael",
            "author_corresponding": "Wei Chen",
            "author_corresponding_institution": "Johns Hopkins Bloomberg School of Public Health",
            "date": "2024-01-01",
            "version": "1",
            "type": "new",
            "license": "cc_by_nc_nd",
            "category": "epidemiology",
            "jatsxml": "https://www.medrxiv.org/content/10.1101/2024.01.01.345678v1.source.xml",
            "abstract": "The emergence of the Omicron variant raised concerns about COVID-19 vaccine effectiveness. We conducted a systematic review and meta-analysis of studies evaluating vaccine effectiveness against Omicron infection and severe outcomes. We analyzed 45 studies comprising over 10 million individuals. Our results show moderate effectiveness against infection (45%, 95% CI: 40-50%) but high effectiveness against hospitalization (85%, 95% CI: 82-88%). Booster doses significantly improved protection.",
            "published": "NA",
            "server": "medrxiv",
        },
        {
            "doi": "10.1101/2024.01.01.456789",
            "title": "Machine learning prediction of patient outcomes in intensive care units",
            "authors": "Garcia, Carlos; Liu, Xin; Patel, Amit",
            "author_corresponding": "Carlos Garcia",
            "author_corresponding_institution": "Stanford University School of Medicine",
            "date": "2024-01-02",
            "version": "1",
            "type": "new",
            "license": "cc_by",
            "category": "health informatics",
            "jatsxml": "https://www.medrxiv.org/content/10.1101/2024.01.01.456789v1.source.xml",
            "abstract": "Predicting patient outcomes in ICUs remains challenging. We developed machine learning models using electronic health records from 50,000 ICU admissions. Our ensemble model combining XGBoost and neural networks achieved an AUC of 0.92 for predicting 30-day mortality. Key predictive features included vital signs, laboratory values, and medication patterns. The model shows promise for clinical decision support.",
            "published": "NA",
            "server": "medrxiv",
        },
    ],
}

# Empty response
BIORXIV_EMPTY_RESPONSE = {
    "messages": [
        {
            "status": "ok",
            "interval": "2020-01-01/2020-01-01",
            "cursor": 0,
            "count": 0,
            "total": "0",
        }
    ],
    "collection": [],
}

# Response for published papers endpoint
BIORXIV_PUBS_RESPONSE = {
    "messages": [
        {"status": "ok", "interval": "2024-01-01/2024-01-02", "cursor": 0, "count": 1}
    ],
    "collection": [
        {
            "doi": "10.1101/2023.12.01.123456",
            "title": "Previously posted preprint now published",
            "authors": "Author, First; Author, Second",
            "author_corresponding": "First Author",
            "author_corresponding_institution": "University",
            "date": "2023-12-01",
            "version": "3",
            "type": "published",
            "license": "cc_by",
            "category": "molecular biology",
            "published_doi": "10.1038/nature.2024.12345",
            "published_citation": "Nature 2024;600:123-128",
            "server": "biorxiv",
        }
    ],
}

# Convert to JSON strings for testing
BIORXIV_API_RESPONSE_JSON = json.dumps(BIORXIV_API_RESPONSE)
MEDRXIV_API_RESPONSE_JSON = json.dumps(MEDRXIV_API_RESPONSE)
BIORXIV_EMPTY_RESPONSE_JSON = json.dumps(BIORXIV_EMPTY_RESPONSE)
BIORXIV_PUBS_RESPONSE_JSON = json.dumps(BIORXIV_PUBS_RESPONSE)
