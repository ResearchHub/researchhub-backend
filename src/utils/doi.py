import random
import string
import time
from datetime import datetime

import requests
from django.template.loader import render_to_string

from researchhub.settings import (
    BASE_FRONTEND_URL,
    CROSSREF_API_URL,
    CROSSREF_DOI_PREFIX,
    CROSSREF_DOI_SUFFIX_LENGTH,
    CROSSREF_LOGIN_ID,
    CROSSREF_LOGIN_PASSWORD,
)


class DOI:
    def __init__(self, base_doi=None, version=None):
        self.base_doi = base_doi
        if base_doi is None:
            self.base_doi = self.generate_base_doi()

        self.doi = base_doi

        if version is not None:
            self.doi = "base_doi.{version}"

    def generate_base_doi(self):
        return CROSSREF_DOI_PREFIX + "".join(
            random.choice(string.ascii_lowercase + string.digits)
            for _ in range(CROSSREF_DOI_SUFFIX_LENGTH)
        )

    def register_doi_for_post(self, authors, title, rh_post):
        url = f"{BASE_FRONTEND_URL}/post/{rh_post.id}/{rh_post.slug}"
        return self.register_doi(authors, title, url)

    def register_doi_for_paper(self, authors, title, rh_paper):
        url = f"{BASE_FRONTEND_URL}/paper/{rh_paper.id}/{rh_paper.slug}"
        return self.register_doi(authors, title, url)

    def register_doi(self, authors, title, url):
        dt = datetime.today()
        contributors = []

        for author in authors:
            institution = None
            if author.university:
                place = None
                if author.university.city:
                    place = "{author.university.city}, {author.university.state}"
                institution = {
                    "name": author.university.name,
                    "place": place,
                }

            contributors.append(
                {
                    "first_name": author.first_name,
                    "last_name": author.last_name,
                    "orcid": author.orcid_id,
                    "institution": institution,
                }
            )

        context = {
            "timestamp": int(time.time()),
            "contributors": contributors,
            "title": title,
            "publication_month": dt.month,
            "publication_day": dt.day,
            "publication_year": dt.year,
            "doi": self.base_doi,
            "url": url,
        }
        crossref_xml = render_to_string("crossref.xml", context)
        files = {
            "operation": (None, "doMDUpload"),
            "login_id": (None, CROSSREF_LOGIN_ID),
            "login_passwd": (None, CROSSREF_LOGIN_PASSWORD),
            "fname": ("crossref.xml", crossref_xml),
        }
        crossref_response = requests.post(CROSSREF_API_URL, files=files)
        return crossref_response
