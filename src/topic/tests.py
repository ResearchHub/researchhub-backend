import json
from datetime import datetime

from rest_framework.test import APITestCase

from topic.models import Topic


class ProcessOpenAlexWorksTests(APITestCase):
    def setUp(self):
        with open("./topic/openalex_topics.json", "r") as file:
            response = json.load(file)
            self.topics = response.get("results")

    def test_create_topic(self):
        topic = self.topics[0]
        Topic.upsert_from_openalex(topic)

        created_topic = Topic.objects.filter(openalex_id=topic["id"]).first()
        self.assertEqual(created_topic.openalex_id, topic["id"])

    def test_update_topic(self):
        old_topic = self.topics[0]
        old_topic["display_name"] = "old topic"
        Topic.upsert_from_openalex(old_topic)

        # Modify the original topic so that date is in the future
        # This will trigger an update.
        now = datetime.now()
        new_topic = self.topics[0]
        new_topic["updated_date"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")
        new_topic["display_name"] = "new topic"

        Topic.upsert_from_openalex(new_topic)

        created_topic = Topic.objects.filter(openalex_id=new_topic["id"]).first()
        self.assertEqual(created_topic.display_name, "new topic")

    def test_create_topic_should_create_related_entities(self):
        topic = self.topics[0]
        created_topic = Topic.upsert_from_openalex(topic)

        subfield = created_topic.subfield
        field = subfield.field
        domain = field.domain

        self.assertEqual(domain.openalex_id, topic["domain"]["id"])
        self.assertEqual(subfield.openalex_id, topic["subfield"]["id"])
        self.assertEqual(field.openalex_id, topic["field"]["id"])
