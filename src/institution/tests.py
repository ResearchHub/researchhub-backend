import json
from datetime import datetime

from rest_framework.test import APITestCase

from institution.models import Institution


class ProcessOpenAlexWorksTests(APITestCase):
    def setUp(self):
        with open("./institution/openalex_institutions.json", "r") as file:
            response = json.load(file)
            self.institutions = response.get("results")

    def test_create_institution(self):
        institution = self.institutions[0]
        Institution.upsert_from_openalex(institution)

        created_inst = Institution.objects.filter(openalex_id=institution["id"]).first()
        self.assertEqual(created_inst.openalex_id, institution["id"])

    def test_update_institution(self):
        old_institution = self.institutions[0]
        old_institution["display_name"] = "old institution"
        Institution.upsert_from_openalex(old_institution)

        # Modify the original object so that date is in the future
        # This will trigger an update.
        now = datetime.now()
        new_institution = self.institutions[0]
        new_institution["updated_date"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")
        new_institution["display_name"] = "new topic"

        Institution.upsert_from_openalex(new_institution)

        created_inst = Institution.objects.filter(
            openalex_id=new_institution["id"]
        ).first()
        self.assertEqual(created_inst.display_name, "new topic")
